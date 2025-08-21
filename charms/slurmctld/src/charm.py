#!/usr/bin/env python3
# Copyright 2025 Vantage Compute Corporation
# Copyright 2020-2024 Omnivector, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Charmed operator for `slurmctld`, Slurm's controller service."""

import logging
import secrets
from typing import cast

import ops
from config import (
    reconfigure,
    seed_default_config,
    update_cgroup_config,
    update_default_partition,
    update_nhc_args,
    update_overrides,
)
from constants import (
    ACCOUNTING_CONFIG_FILE,
    CLUSTER_NAME_PREFIX,
    DEFAULT_PROFILING_CONFIG,
    PEER_INTEGRATION_NAME,
    PROFILING_CONFIG_FILE,
    PROMETHEUS_EXPORTER_PORT,
    SACKD_INTEGRATION_NAME,
    SLURMCTLD_PORT,
    SLURMD_INTEGRATION_NAME,
    SLURMDBD_INTEGRATION_NAME,
    SLURMRESTD_INTEGRATION_NAME,
)
from hpc_libs.interfaces import (
    ControllerData,
    SackdConnectedEvent,
    SackdRequirer,
    SlurmdbdConnectedEvent,
    SlurmdbdDisconnectedEvent,
    SlurmdbdReadyEvent,
    SlurmdbdRequirer,
    SlurmdDisconnectedEvent,
    SlurmdReadyEvent,
    SlurmdRequirer,
    SlurmrestdConnectedEvent,
    SlurmrestdRequirer,
    block_when,
    database_not_ready,
    partition_not_ready,
    wait_when,
)
from hpc_libs.utils import StopCharm, leader, plog, refresh
from integrations import SlurmctldPeer, SlurmctldPeerConnectedEvent
from interface_influxdb import InfluxDB, InfluxDBAvailableEvent, InfluxDBUnavailableEvent
from netifaces import interfaces
from slurm_ops import SlurmctldManager, SlurmOpsError, scontrol
from slurmutils import (
    AcctGatherConfig,
    ModelError,
    NodeSet,
    SlurmConfig,
)
from state import check_slurmctld, cluster_name_not_set, config_not_ready, slurmctld_not_installed

from charms.grafana_agent.v0.cos_agent import COSAgentProvider

logger = logging.getLogger(__name__)
refresh = refresh(check=check_slurmctld)


class SlurmctldCharm(ops.CharmBase):
    """Charmed operator for `slurmctld`, Slurm's controller service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmctld = SlurmctldManager(snap=False)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on.show_current_config_action, self._on_show_current_config_action)
        framework.observe(self.on.drain_action, self._on_drain_nodes_action)
        framework.observe(self.on.resume_action, self._on_resume_nodes_action)

        self.slurmctld_peer = SlurmctldPeer(self, PEER_INTEGRATION_NAME)
        framework.observe(
            self.slurmctld_peer.on.slurmctld_peer_connected,
            self._on_slurmctld_peer_connected,
        )

        self.sackd = SackdRequirer(self, SACKD_INTEGRATION_NAME)
        framework.observe(self.sackd.on.sackd_connected, self._on_sackd_connected)

        self.slurmd = SlurmdRequirer(self, SLURMD_INTEGRATION_NAME)
        framework.observe(self.slurmd.on.slurmd_ready, self._on_slurmd_ready)
        framework.observe(self.slurmd.on.slurmd_disconnected, self._on_slurmd_disconnected)

        self.slurmdbd = SlurmdbdRequirer(self, SLURMDBD_INTEGRATION_NAME)
        framework.observe(self.slurmdbd.on.slurmdbd_connected, self._on_slurmdbd_connected)
        framework.observe(self.slurmdbd.on.slurmdbd_ready, self._on_slurmdbd_ready)
        framework.observe(self.slurmdbd.on.slurmdbd_disconnected, self._on_slurmdbd_disconnected)

        self.slurmrestd = SlurmrestdRequirer(self, SLURMRESTD_INTEGRATION_NAME)
        framework.observe(self.slurmrestd.on.slurmrestd_connected, self._on_slurmrestd_connected)

        self._influxdb = InfluxDB(self, "influxdb")
        framework.observe(self._influxdb._on.influxdb_available, self._on_influxdb_available)
        framework.observe(self._influxdb._on.influxdb_unavailable, self._on_influxdb_unavailable)

        self._grafana_agent = COSAgentProvider(
            self,
            metrics_endpoints=[{"path": "/metrics", "port": 9092}],
            metrics_rules_dir="./src/cos/alert_rules/prometheus",
            dashboard_dirs=["./src/cos/grafana_dashboards"],
            recurse_rules_dirs=True,
        )

    @refresh
    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install `slurmctld` after charm is deployed on the unit."""
        if not self.unit.is_leader():
            raise StopCharm(
                ops.BlockedStatus(
                    "`slurmctld` high-availability is not supported. Scale down application"
                )
            )

        self.unit.status = ops.MaintenanceStatus("Installing `slurmctld`")

        try:
            self.slurmctld.install()

            self.slurmctld.jwt.generate()
            self.slurmctld.key.generate()

            self.slurmctld.exporter.service.stop()
            self.slurmctld.exporter.service.disable()
            self.slurmctld.exporter.args = [
                "-slurm.collect-diags",
                "-slurm.collect-limits",
            ]

            self.slurmctld.service.stop()
            self.slurmctld.service.disable()
            self.unit.set_workload_version(self.slurmctld.version())
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to install `slurmctld`. See `juju debug-log` for details."
                )
            )

        self.unit.open_port("tcp", SLURMCTLD_PORT)
        self.unit.open_port("tcp", PROMETHEUS_EXPORTER_PORT)

    @refresh
    @wait_when(cluster_name_not_set)
    @block_when(slurmctld_not_installed)
    def _on_start(self, event: ops.StartEvent) -> None:
        """Write slurm.conf and start `slurmctld` service.

        Notes:
            - The start hook can execute multiple times in a charms lifecycle,
              for example, after a reboot of the underlying instance.
        """
        if not self.unit.is_leader():
            raise StopCharm(
                ops.BlockedStatus(
                    "`slurmctld` high-availability is not supported. Scale down application"
                )
            )

        try:
            seed_default_config(self)

            self.slurmctld.service.enable()
            self.slurmctld.service.restart()
            self.slurmctld.exporter.service.enable()
            self.slurmctld.exporter.service.restart()
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus("Failed to start `slurmctld`. See `juju debug-log` for details")
            )

    @leader
    @refresh
    @reconfigure
    def _on_config_changed(self, _: ops.ConfigChangedEvent) -> None:
        """Update the `slurmctld` application's configuration.

        Notes:
            - Only the `slurmctld` application leader should handle configuration changes. The
              non-leader units should only read configuration managed by the leader.
        """
        update_cgroup_config(self)
        update_default_partition(self)
        update_nhc_args(self)
        update_overrides(self)

    @refresh
    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Check status of the `slurmctld` application."""

    @refresh
    def _on_slurmctld_peer_connected(self, _: SlurmctldPeerConnectedEvent) -> None:
        """Handle when `slurmctld` peer integration is created."""
        self.slurmctld_peer.cluster_name = (
            cluster_name
            if (cluster_name := self.config.get("cluster-name", "")) != ""
            else f"{CLUSTER_NAME_PREFIX}-{secrets.token_urlsafe(3)}"
        )

    @refresh
    @block_when(slurmctld_not_installed)
    def _on_sackd_connected(self, event: SackdConnectedEvent) -> None:
        """Handle when a new `sackd` application is connected."""
        self.sackd.set_controller_data(
            ControllerData(
                auth_key=self.slurmctld.key.get(),
                controllers=[f"{self.slurmctld.hostname}:{SLURMCTLD_PORT}"],
            ),
            integration_id=event.relation.id,
        )

    @refresh
    @reconfigure
    @wait_when(cluster_name_not_set, partition_not_ready)
    @block_when(slurmctld_not_installed)
    def _on_slurmd_ready(self, event: SlurmdReadyEvent) -> None:
        """Handle when partition data is ready from a `slurmd` application."""
        data = self.slurmd.get_compute_data(event.relation.id)
        name = data.partition.partition_name
        include = f"slurm.conf.{name}"

        default_partition = cast(str, self.config.get("default-partition", ""))
        if default_partition == name:
            data.partition.default = True

        with self.slurmctld.config.includes[include].edit() as config:
            config.nodesets[name] = NodeSet(nodeset=name, feature=name)
            config.partitions[name] = data.partition

        try:
            with self.slurmctld.config.edit() as config:
                config.include = [include] + config.include
        except ModelError:
            pass

        self.slurmd.set_controller_data(
            ControllerData(
                auth_key=self.slurmctld.key.get(),
                controllers=[f"{self.slurmctld.hostname}:{SLURMCTLD_PORT}"],
                nhc_args=cast(str, self.config.get("health-check-params", "")),
            ),
            integration_id=event.relation.id,
        )

    @refresh
    @reconfigure
    @block_when(slurmctld_not_installed)
    def _on_slurmd_disconnected(self, event: SlurmdDisconnectedEvent) -> None:
        """Handle when a `slurmd` application is disconnected."""
        data = self.slurmd.get_compute_data(event.relation.id)
        include = f"slurm.conf.{data.partition.partition_name}"

        try:
            with self.slurmctld.config.edit() as config:
                config.include.remove(include)
        except ValueError:
            pass

        self.slurmctld.config.includes[include].delete()

    @refresh
    @block_when(slurmctld_not_installed)
    def _on_slurmdbd_connected(self, event: SlurmdbdConnectedEvent) -> None:
        """Handle when a new `slurmdbd` application is connected."""
        self.slurmdbd.set_controller_data(
            ControllerData(
                auth_key=self.slurmctld.key.get(),
                jwt_key=self.slurmctld.jwt.get(),
            ),
            integration_id=event.relation.id,
        )

    @refresh
    @reconfigure
    @wait_when(database_not_ready)
    @block_when(slurmctld_not_installed)
    def _on_slurmdbd_ready(self, event: SlurmdbdReadyEvent) -> None:
        """Handle when database data is ready from a `slurmdbd` application."""
        data = self.slurmdbd.get_database_data(event.relation.id)

        with self.slurmctld.config.includes[ACCOUNTING_CONFIG_FILE].edit() as config:
            config.accounting_storage_host = data.hostname
            config.accounting_storage_port = 6819
            config.accounting_storage_type = "accounting_storage/slurmdbd"

        # Restore `acct_gather.conf` configuration if a snapshot exists.
        self.slurmctld.acct_gather.restore()
        try:
            with self.slurmctld.config.edit() as config:
                config.include = [PROFILING_CONFIG_FILE] + config.include
        except ModelError:
            pass

    @refresh
    @reconfigure
    @block_when(slurmctld_not_installed)
    def _on_slurmdbd_disconnected(self, _: SlurmdbdDisconnectedEvent) -> None:
        """Handle when a `slurmdbd` application is disconnected."""
        with self.slurmctld.config.includes[ACCOUNTING_CONFIG_FILE].edit() as config:
            del config.accounting_storage_host
            del config.accounting_storage_port
            del config.accounting_storage_type

        # Save a copy of `acct_gather.conf`. `acct_gather` plugins require that `slurmctld` is
        # integrated with `slurmdbd`. The `acct_gather` plugin will be re-enabled when an
        # integration with slurmdbd is re-established.
        self.slurmctld.acct_gather.save()
        self.slurmctld.acct_gather.delete()
        try:
            with self.slurmctld.config.edit() as config:
                config.includes.remove(PROFILING_CONFIG_FILE)
        except ValueError:
            pass

    @refresh
    @wait_when(database_not_ready, config_not_ready)
    @block_when(slurmctld_not_installed)
    def _on_slurmrestd_connected(self, event: SlurmrestdConnectedEvent) -> None:
        """Handle when a new `slurmrestd` application is connected."""
        self.slurmrestd.set_controller_data(
            ControllerData(
                auth_key=self.slurmctld.key.get(),
                slurmconfig={
                    "slurm.conf": self.slurmctld.config.load(),
                    **{k: v.load() for k, v in self.slurmctld.config.includes.items()},
                },
            ),
            integration_id=event.relation.id,
        )

    @leader
    @refresh
    @reconfigure
    @wait_when(database_not_ready)
    @block_when(slurmctld_not_installed)
    def _on_influxdb_available(self, event: InfluxDBAvailableEvent) -> None:
        """Assemble the influxdb acct_gather.conf options."""
        logger.info("`influxdb` database is available. enabling job profiling")
        try:
            config = AcctGatherConfig(
                profileinfluxdbdefault=["all"],
                profileinfluxdbhost=event.influxdb_host,
                profileinfluxdbuser=event.influxdb_user,
                profileinfluxdbpass=event.influxdb_pass,
                profileinfluxdbdatabase=event.influxdb_database,
                profileinfluxdbrtpolicy=event.influxdb_policy,
                sysfsinterfaces=interfaces(),
            )

            logger.info("updating `acct_gather.conf`")
            logger.debug(
                "`acct_gather.conf`:\n%s",
                plog(
                    config.dict()
                    | ({"profileinfluxdbpass": "***"} if config.profile_influxdb_pass else {})
                ),
            )
            self.slurmctld.acct_gather.dump(config)
            logger.info("`acct_gather.conf` successfully updated")
        except (ModelError, ValueError) as e:
            logger.error("failed to update `acct_gather.conf`. reason:\n%s", e)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to update `acct_gather.conf`. See `juju debug-log` for details"
                )
            )

        config = SlurmConfig(**DEFAULT_PROFILING_CONFIG)
        logger.info("updating `%s`", PROFILING_CONFIG_FILE)
        logger.debug("`%s`:\n%s", PROFILING_CONFIG_FILE, plog(config.dict()))
        self.slurmctld.config.includes[PROFILING_CONFIG_FILE].dump(config)
        logger.info("`%s` successfully updated", PROFILING_CONFIG_FILE)

    @leader
    @reconfigure
    @block_when(slurmctld_not_installed)
    def _on_influxdb_unavailable(self, _: InfluxDBUnavailableEvent) -> None:
        """Clear the `acct_gather.conf` options on departed relation."""
        logger.info("`influxdb` database is no longer available. disabling job profiling")

        logger.info("deleting `acct_gather.conf`")
        self.slurmctld.acct_gather.delete()
        logger.info("`acct_gather.conf` successfully deleted")

        logger.info("clearing `%s`", PROFILING_CONFIG_FILE)
        with self.slurmctld.config.includes[PROFILING_CONFIG_FILE].edit() as profiling:
            del profiling.acct_gather_profile_type
            del profiling.acct_gather_interconnect_type
            del profiling.accounting_storage_tres
            del profiling.acct_gather_node_freq
            del profiling.job_acct_gather_frequency
            del profiling.job_acct_gather_type

        logger.info("`%s` successfully cleared", PROFILING_CONFIG_FILE)

    def _on_show_current_config_action(self, event: ops.ActionEvent) -> None:
        """Show current slurm.conf."""
        event.set_results({"slurm.conf": str(self.slurmctld.config.load())})

    def _on_drain_nodes_action(self, event: ops.ActionEvent) -> None:
        """Drain specified nodes."""
        nodes = event.params["nodename"]
        reason = event.params["reason"]

        logger.debug(f"#### Draining {nodes} because {reason}.")
        event.log(f"Draining {nodes} because {reason}.")

        try:
            scontrol("update", f"nodename={nodes}", "state=drain", f'reason="{reason}"')
        except SlurmOpsError as e:
            event.fail(message=f"Error draining {nodes}: {e.message}")

        event.set_results({"status": "draining", "nodes": nodes})

    def _on_resume_nodes_action(self, event: ops.ActionEvent) -> None:
        """Resume specified nodes."""
        nodes = event.params["nodename"]

        logger.debug(f"#### Resuming {nodes}.")
        event.log(f"Resuming {nodes}.")

        try:
            scontrol("update", f"nodename={nodes}", "state=idle")
        except SlurmOpsError as e:
            event.fail(message=f"Error resuming {nodes}: {e.message}")

        event.set_results({"status": "resuming", "nodes": nodes})


if __name__ == "__main__":
    ops.main(SlurmctldCharm)
