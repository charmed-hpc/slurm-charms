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
    get_controllers,
    init_config,
    reconfigure_slurmctld,
    update_cgroup_config,
    update_default_partition,
    update_nhc_args,
    update_overrides,
)
from constants import (
    ACCOUNTING_CONFIG_FILE,
    CLUSTER_NAME_PREFIX,
    DEFAULT_PROFILING_CONFIG,
    HA_MOUNT_INTEGRATION_NAME,
    OCI_RUNTIME_INTEGRATION_NAME,
    PEER_INTEGRATION_NAME,
    PROFILING_CONFIG_FILE,
    PROMETHEUS_EXPORTER_PORT,
    SACKD_INTEGRATION_NAME,
    SLURMCTLD_PORT,
    SLURMD_INTEGRATION_NAME,
    SLURMDBD_INTEGRATION_NAME,
    SLURMRESTD_INTEGRATION_NAME,
)
from high_availability import SlurmctldHA
from hpc_libs.interfaces import (
    ControllerData,
    OCIRuntimeDisconnectedEvent,
    OCIRuntimeReadyEvent,
    OCIRuntimeRequirer,
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
    block_unless,
    database_ready,
    partition_ready,
    wait_unless,
)
from hpc_libs.utils import StopCharm, leader, plog, reconfigure, refresh
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
from state import (
    all_units_observed,
    check_slurmctld,
    cluster_name_set,
    config_ready,
    peer_ready,
    shared_state_mounted,
    slurmctld_installed,
    slurmctld_is_active,
)

from charms.grafana_agent.v0.cos_agent import COSAgentProvider

logger = logging.getLogger(__name__)
reconfigure = reconfigure(hook=reconfigure_slurmctld)
reconfigure.__doc__ = """Reconfigure the `slurmctld` service after an event handler completes."""
refresh = refresh(hook=check_slurmctld)
refresh.__doc__ = """Refresh status of the `slurmctld` unit after an event handler completes."""


class SlurmctldCharm(ops.CharmBase):
    """Charmed operator for `slurmctld`, Slurm's controller service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmctld = SlurmctldManager(snap=False)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.leader_elected, self._on_leader_elected)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on.show_current_config_action, self._on_show_current_config_action)
        framework.observe(self.on.set_node_state_action, self._on_set_node_state_action)

        self.slurmctld_peer = SlurmctldPeer(self, PEER_INTEGRATION_NAME)
        framework.observe(
            self.slurmctld_peer.on.slurmctld_peer_connected,
            self._on_slurmctld_peer_connected,
        )
        framework.observe(self.slurmctld_peer.on.slurmctld_peer_joined, self._on_slurmctld_changed)
        framework.observe(
            self.slurmctld_peer.on.slurmctld_peer_departed, self._on_slurmctld_changed
        )
        self.slurmctld_ha = SlurmctldHA(self, HA_MOUNT_INTEGRATION_NAME)

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

        self.oci_runtime = OCIRuntimeRequirer(self, OCI_RUNTIME_INTEGRATION_NAME)
        framework.observe(self.oci_runtime.on.oci_runtime_ready, self._on_oci_runtime_ready)
        framework.observe(
            self.oci_runtime.on.oci_runtime_disconnected,
            self._on_oci_runtime_disconnected,
        )

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
        self.unit.status = ops.MaintenanceStatus("Installing `slurmctld`")

        try:
            self.slurmctld.install()

            self.slurmctld.exporter.service.stop()
            self.slurmctld.exporter.service.disable()
            self.slurmctld.exporter.args = [
                "-slurm.collect-diags",
                "-slurm.collect-limits",
            ]

            self.slurmctld.service.stop()
            self.slurmctld.service.disable()

            if self.unit.is_leader():
                # Check for existence of keys to avoid erroneous regeneration in the case where a
                # new unit is elected leader as it is being deployed
                if not self.slurmctld.jwt.path.exists():
                    self.slurmctld.jwt.generate()
                if not self.slurmctld.key.path.exists():
                    self.slurmctld.key.generate()

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
    @reconfigure
    @wait_unless(shared_state_mounted)
    def _on_leader_elected(self, event: ops.LeaderElectedEvent) -> None:
        """Refresh controller lists on leader re-election."""
        if not self.model.relations.get(HA_MOUNT_INTEGRATION_NAME):
            logger.debug("HA is not enabled. skipping event")
            return

        self._refresh_controllers()

    @refresh
    @block_unless(slurmctld_installed, shared_state_mounted)
    @wait_unless(cluster_name_set, peer_ready)
    def _on_start(self, event: ops.StartEvent) -> None:
        """Write slurm.conf and start `slurmctld` service.

        Notes:
            - The start hook can execute multiple times in a charms lifecycle,
              for example, after a reboot of the underlying instance.
        """
        try:
            # Prevent slurm.conf being overwritten after a reboot of the underlying instance
            if self.unit.is_leader() and not self.slurmctld.config.exists():
                init_config(self)

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

    @leader
    @refresh
    def _on_slurmctld_peer_connected(self, _: SlurmctldPeerConnectedEvent) -> None:
        """Handle when `slurmctld` peer integration is created."""
        # Don't overwrite an existing cluster name
        data = self.slurmctld_peer.get_controller_peer_app_data()
        if data and data.cluster_name:
            return

        cluster_name = (
            cluster_name
            if (cluster_name := self.config.get("cluster-name", "")) != ""
            else f"{CLUSTER_NAME_PREFIX}-{secrets.token_urlsafe(3)}"
        )
        self.slurmctld_peer.update_controller_peer_app_data(cluster_name=cluster_name)

    @refresh
    @reconfigure
    def _on_slurmctld_changed(self, event) -> None:
        """Handle when `slurmctld` units join or leave."""
        # Only a slurm.conf update needed - no other conf files are affected.
        # slurmrestd gets the updated config via the reconfigure hook
        self._refresh_controllers()

    @refresh
    @wait_unless(slurmctld_is_active)
    @block_unless(slurmctld_installed)
    def _on_sackd_connected(self, event: SackdConnectedEvent) -> None:
        """Handle when a new `sackd` application is connected."""
        new_endpoints = [f"{c}:{SLURMCTLD_PORT}" for c in get_controllers(self)]
        self.sackd.set_controller_data(
            ControllerData(
                auth_key=self.slurmctld.key.get(),
                controllers=new_endpoints,
            ),
            integration_id=event.relation.id,
        )

    @refresh
    @reconfigure
    @wait_unless(partition_ready, slurmctld_is_active)
    @block_unless(slurmctld_installed)
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

        new_endpoints = [f"{c}:{SLURMCTLD_PORT}" for c in get_controllers(self)]
        self.slurmd.set_controller_data(
            ControllerData(
                auth_key=self.slurmctld.key.get(),
                controllers=new_endpoints,
                nhc_args=cast(str, self.config.get("health-check-params", "")),
            ),
            integration_id=event.relation.id,
        )

    @refresh
    @reconfigure
    @block_unless(slurmctld_installed)
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
    @block_unless(slurmctld_installed)
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
    @wait_unless(database_ready, all_units_observed)
    @block_unless(slurmctld_installed)
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
    @block_unless(slurmctld_installed)
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
                config.include.remove(PROFILING_CONFIG_FILE)
        except ValueError:
            pass

    @refresh
    @wait_unless(config_ready, database_ready, slurmctld_is_active)
    @block_unless(slurmctld_installed)
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
    @wait_unless(database_ready)
    @block_unless(slurmctld_installed)
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
    @block_unless(slurmctld_installed)
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

    @reconfigure
    @block_unless(slurmctld_installed)
    def _on_oci_runtime_ready(self, event: OCIRuntimeReadyEvent) -> None:
        """Handle when OCI runtime data is ready from a Slurm OCI runtime provider."""
        data = self.oci_runtime.get_oci_runtime_data(event.relation.id)

        logger.info("updating `oci.conf`")
        logger.debug("`oci.conf`:\n%s", plog(data.ociconfig.dict()))
        self.slurmctld.oci.dump(data.ociconfig)
        logger.info("`oci.conf` successfully updated")

    @reconfigure
    @block_unless(slurmctld_installed)
    def _on_oci_runtime_disconnected(self, _: OCIRuntimeDisconnectedEvent) -> None:
        """Handle when a Slurm OCI runtime is disconnected."""
        logger.info("oci runtime has been disconnected. disabling oci support")

        logger.info("deleting `oci.conf`")
        self.slurmctld.oci.delete()
        logger.info("`oci.conf` successfully deleted")

    def _on_show_current_config_action(self, event: ops.ActionEvent) -> None:
        """Show current slurm.conf."""
        event.set_results({"slurm.conf": str(self.slurmctld.config.load())})

    def _on_set_node_state_action(self, event: ops.ActionEvent) -> None:
        """Set the state of the provided compute nodes with `scontrol`."""
        nodes = event.params.get("nodes")
        state = event.params.get("state")
        reason = event.params.get("reason")

        cmd = ["update", f"nodename={nodes}", f"state={state}"]
        if state != "idle":
            cmd.append(f"reason='{reason if reason else 'n/a'}'")

        logger.info("setting state of node(s) %s to state '%s'", nodes, state)
        try:
            scontrol(*cmd)
        except SlurmOpsError as e:
            err = (
                f"failed to set state of node(s) {nodes} to state '{state}'. reason:\n{e.message}"
            )
            logger.error(err)
            event.fail(err.capitalize())

        logger.info("successfully updated state of node(s) %s to '%s'", nodes, state)

    def _merge_controller_data(self, app: SackdRequirer | SlurmdRequirer, new_endpoints) -> None:
        """Merge new controller endpoints with existing controller data."""
        for integration in app.integrations:
            current = integration.load(ControllerData, self.app)
            logger.debug(
                "existing data for %s integration %s: %s",
                app._integration_name,
                integration,
                current,
            )

            data = ControllerData(
                auth_key="",  # Don't set keys here or secrets will be replaced with "***"
                auth_key_id=current.auth_key_id,
                controllers=new_endpoints,  # Update only the controllers
                jwt_key="",
                jwt_key_id=current.jwt_key_id,
                nhc_args=current.nhc_args,
                slurmconfig=current.slurmconfig,
            )

            logger.debug(
                "updating %s integration %s with new data: %s",
                app._integration_name,
                integration,
                data,
            )
            app.set_controller_data(data, integration_id=integration.id)

    def _refresh_controllers(self) -> None:
        """Refresh the list of controllers in slurm.conf and relevant Slurm services.

        Notes:
            - This function must only be called by a hook with a @reconfigure decorator to ensure
              slurmrestd is also updated with the new Slurm configuration.
        """
        new_controllers = get_controllers(self)
        with self.slurmctld.config.edit() as config:
            config.slurmctld_host = new_controllers

        # sackd and slurmd require a list of endpoints (host:port), rather than just hostnames
        new_endpoints = [f"{c}:{SLURMCTLD_PORT}" for c in new_controllers]
        self._merge_controller_data(self.sackd, new_endpoints)
        self._merge_controller_data(self.slurmd, new_endpoints)


if __name__ == "__main__":  # noqa
    ops.main(SlurmctldCharm)
