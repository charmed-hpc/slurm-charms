#!/usr/bin/env python3
# Copyright 2025-2026 Vantage Compute Corporation
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

import mail
import ops
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.smtp_integrator.v0.smtp import SmtpDataAvailableEvent, SmtpRequires
from config import ConfigManager
from constants import (
    CLUSTER_NAME_PREFIX,
    HA_MOUNT_INTEGRATION_NAME,
    MAIL_INTEGRATION_NAME,
    MAILPROG_PATH,
    OCI_RUNTIME_INTEGRATION_NAME,
    PEER_INTEGRATION_NAME,
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
from hpc_libs.is_container import is_container
from hpc_libs.utils import StopCharm, leader, plog, refresh
from integrations import SlurmctldPeer, SlurmctldPeerConnectedEvent
from interface_influxdb import InfluxDB, InfluxDBAvailableEvent, InfluxDBUnavailableEvent
from psutil import net_if_addrs
from pydantic import ValidationError
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
    slurmctld_ready,
)

logger = logging.getLogger(__name__)
refresh = refresh(hook=check_slurmctld)
refresh.__doc__ = """Refresh status of the `slurmctld` unit after an event handler completes."""


class SlurmctldCharm(ops.CharmBase):
    """Charmed operator for `slurmctld`, Slurm's controller service."""

    _stored = ops.StoredState()

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        # Required to track if this unit is departing during relation broken events
        self._stored.set_default(unit_departing=False)

        self.slurmctld = SlurmctldManager(snap=False)
        try:
            self.configmgr = self.load_config(ConfigManager)
        except ValidationError as e:
            logger.error(e)
            self.unit.status = ops.BlockedStatus(
                "Configuration option(s) "
                + ", ".join(
                    [
                        f"'{option.replace('_', '-')}'"  # type: ignore
                        for error in e.errors()
                        for option in error.get("loc", ())
                    ]
                )
                + " failed validation. See `juju debug-log` for details"
            )
            return

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

        self._smtp = SmtpRequires(self)
        framework.observe(
            self.on[MAIL_INTEGRATION_NAME].relation_created, self._on_smtp_relation_created
        )
        framework.observe(self._smtp.on.smtp_data_available, self._on_smtp_data_available)
        framework.observe(
            self.on[MAIL_INTEGRATION_NAME].relation_departed, self._on_smtp_relation_departed
        )
        framework.observe(
            self.on[MAIL_INTEGRATION_NAME].relation_broken, self._on_smtp_relation_broken
        )

        self._opentelemetry_collector = COSAgentProvider(
            self,
            metrics_endpoints=[
                {"path": f"/metrics/{endpoint}", "port": SLURMCTLD_PORT}
                for endpoint in ["jobs", "nodes", "partitions", "scheduler", "jobs-users-accts"]
            ],
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
    @wait_unless(shared_state_mounted)
    def _on_leader_elected(self, event: ops.LeaderElectedEvent) -> None:
        """Refresh controller lists on leader re-election."""
        if not self.model.relations.get(HA_MOUNT_INTEGRATION_NAME):
            logger.debug("HA is not enabled. skipping event")
            return

        self._refresh_controllers()
        self._reconfigure()

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
            # Prevent `slurm.conf` being overwritten after a reboot of the underlying instance.
            if self.unit.is_leader() and not self.slurmctld.config.exists():
                data = self.slurmctld_peer.get_controller_peer_app_data()
                with self.slurmctld.config.edit() as config:
                    config.cluster_name = data.cluster_name if data else ""
                    config.slurmctld_host = self._get_controllers()
                    config.auth_alt_parameters = {"jwt_key": "/etc/slurm/jwt_hs256.key"}
                    config.auth_alt_types = ["auth/jwt"]
                    config.auth_type = "auth/slurm"
                    config.cred_type = "cred/slurm"
                    config.gres_types = ["gpu"]
                    config.max_node_count = 65533
                    config.metrics_type = "metrics/openmetrics"
                    config.plugin_dir = ["/usr/lib/x86_64-linux-gnu/slurm-wlm"]
                    config.plug_stack_config = "/etc/slurm/plugstack.conf.d/plugstack.conf"
                    config.proctrack_type = (
                        "proctrack/linuxproc" if is_container() else "proctrack/cgroup"
                    )
                    config.reboot_program = "/usr/sbin/reboot --reboot"
                    config.select_type = "select/cons_tres"
                    config.select_type_parameters = {"cr_cpu_memory": True}
                    config.slurmctld_parameters = {"enable_configless": True}
                    config.slurmctld_port = SLURMCTLD_PORT
                    config.slurmd_port = 6818
                    config.state_save_location = "/var/lib/slurm/checkpoint"
                    config.slurmd_spool_dir = "/var/lib/slurm/slurmd"
                    config.slurmctld_log_file = "/var/log/slurm/slurmctld.log"
                    config.slurmd_log_file = "/var/log/slurm/slurmd.log"
                    config.slurmd_pid_file = "/var/run/slurmd.pid"
                    config.slurmctld_pid_file = "/var/run/slurmctld.pid"
                    config.slurm_user = self.slurmctld.user
                    config.slurmd_user = "root"
                    config.task_plugin = (
                        ["task/affinity"] if is_container() else ["task/cgroup", "task/affinity"]
                    )
                    config.include = [
                        self.slurmctld.accounting.name,
                        self.slurmctld.profiling.name,
                        self.slurmctld.overrides.name,
                    ]

                # The `include` files must exist for `slurmctld` to start successfully.
                self.slurmctld.accounting.create()
                self.slurmctld.profiling.create()
                self.slurmctld.overrides.create()

            # Prevent `gres.conf` being overwritten after a reboot of the underlying instance.
            if self.unit.is_leader() and not self.slurmctld.gres.exists():
                with self.slurmctld.gres.edit() as config:
                    config.auto_detect = "nvidia"

            self.slurmctld.service.enable()
            self.slurmctld.service.restart()
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus("Failed to start `slurmctld`. See `juju debug-log` for details")
            )

    @refresh
    def _on_config_changed(self, _: ops.ConfigChangedEvent) -> None:
        """Update the `slurmctld` application's configuration."""
        # Each unit maintains its own Slurm-Mail configuration, not just the leader.
        # File coherence not a concern - Slurm-Mail can run with a stale slurm-mail.conf. It just
        # briefly attempts to use an old SMTP config or an old `email-from-name` until hooks run to
        # bring config in sync.
        if self.model.relations.get(MAIL_INTEGRATION_NAME):
            with mail.configure() as config:
                config.from_name = self.configmgr.email_from_name
        else:
            logger.debug("smtp integration not connected. skipping mail configuration")

        # Only the leader handles configuration changes for the slurmctld service. Non-leader units
        # read configuration managed by the leader.
        if self.unit.is_leader():
            self.slurmctld.overrides.dump(self.configmgr.slurm_conf_parameters)

            current_default_partition = self.slurmctld.get_default_partition()
            if self.configmgr.default_partition == current_default_partition:
                logger.debug(
                    "default partition '%s' has not changed. "
                    "skipping update to default partition configuration",
                    current_default_partition,
                )
            else:
                logger.info(
                    "default partition has changed from '%s' to '%s'. "
                    "updating default partition configuration",
                    current_default_partition,
                    self.configmgr.default_partition,
                )
                self.slurmctld.set_default_partition(
                    self.configmgr.default_partition,
                    current_default_partition,
                )
                logger.info("default partition configuration updated successfully")

            # Slurm's `proctrack/cgroup` process tracking plugin cannot be used if
            # slurmctld is deployed inside a system container.
            if is_container():
                logger.warning(
                    "machine is a container. not enabling the `proctrack/cgroup` plugin or "
                    "configuring the `%s` file",
                    self.slurmctld.cgroup.name,
                )
            else:
                logger.info("updating `%s` configuration", self.slurmctld.cgroup.name)
                self.slurmctld.cgroup.dump(self.configmgr.cgroup_parameters)
                logger.info("`%s` configuration updated successfully", self.slurmctld.cgroup.name)

        self._reconfigure()

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
    def _on_slurmctld_changed(self, event) -> None:
        """Handle when `slurmctld` units join or leave."""
        # Only a slurm.conf update needed - no other conf files are affected.
        # slurmrestd gets the updated config via the reconfigure hook
        self._refresh_controllers()
        self._reconfigure()

    @refresh
    @wait_unless(slurmctld_is_active)
    @block_unless(slurmctld_installed)
    def _on_sackd_connected(self, event: SackdConnectedEvent) -> None:
        """Handle when a new `sackd` application is connected."""
        new_endpoints = [f"{c}:{SLURMCTLD_PORT}" for c in self._get_controllers()]
        self.sackd.set_controller_data(
            ControllerData(
                auth_key=self.slurmctld.key.get(),
                controllers=new_endpoints,
            ),
            integration_id=event.relation.id,
        )

    @refresh
    @wait_unless(partition_ready, slurmctld_is_active)
    @block_unless(slurmctld_installed)
    def _on_slurmd_ready(self, event: SlurmdReadyEvent) -> None:
        """Handle when partition data is ready from a `slurmd` application."""
        data = self.slurmd.get_compute_data(event.relation.id)
        name = data.partition.partition_name
        include = f"slurm.conf.{name}"

        if name == self.configmgr.default_partition:
            data.partition.default = True

        with self.slurmctld.config.includes[include].edit() as config:
            config.nodesets[name] = NodeSet(nodeset=name, feature=name)
            config.partitions[name] = data.partition

        try:
            with self.slurmctld.config.edit() as config:
                config.include = [include] + config.include
        except ModelError:
            pass

        new_endpoints = [f"{c}:{SLURMCTLD_PORT}" for c in self._get_controllers()]
        self.slurmd.set_controller_data(
            ControllerData(
                auth_key=self.slurmctld.key.get(),
                controllers=new_endpoints,
            ),
            integration_id=event.relation.id,
        )

        self._reconfigure()

    @refresh
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
        self._reconfigure()

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
    @wait_unless(database_ready, all_units_observed)
    @block_unless(slurmctld_installed)
    def _on_slurmdbd_ready(self, event: SlurmdbdReadyEvent) -> None:
        """Handle when database data is ready from a `slurmdbd` application."""
        data = self.slurmdbd.get_database_data(event.relation.id)

        with self.slurmctld.accounting.edit() as config:
            config.accounting_storage_host = data.hostname
            config.accounting_storage_port = 6819
            config.accounting_storage_type = "accounting_storage/slurmdbd"

        # Restore `acct_gather.conf` configuration if a snapshot exists.
        self.slurmctld.acct_gather.restore()
        try:
            with self.slurmctld.config.edit() as config:
                config.include = [self.slurmctld.profiling.name] + config.include
        except ModelError:
            pass

        self._reconfigure()

    @refresh
    @block_unless(slurmctld_installed)
    def _on_slurmdbd_disconnected(self, _: SlurmdbdDisconnectedEvent) -> None:
        """Handle when a `slurmdbd` application is disconnected."""
        with self.slurmctld.accounting.edit() as config:
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
                config.include.remove(self.slurmctld.profiling.name)
        except ValueError:
            pass

        self._reconfigure()

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
                sysfsinterfaces=list(net_if_addrs().keys()),
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

        logger.info("updating `%s` configuration", self.slurmctld.profiling.name)
        config = SlurmConfig()
        config.acct_gather_profile_type = "acct_gather_profile/influxdb"
        config.acct_gather_interconnect_type = "acct_gather_interconnect/sysfs"
        config.accounting_storage_tres = ["ic/sysfs"]
        config.acct_gather_node_freq = 30
        config.job_acct_gather_frequency = {"task": 5, "network": 5}
        config.job_acct_gather_type = (
            "jobacct_gather/linux" if is_container() else "jobacct_gather/cgroup"
        )
        logger.debug("`%s`:\n%s", self.slurmctld.profiling.name, plog(config.dict()))
        self.slurmctld.profiling.dump(config)
        logger.info("`%s` configuration updated successfully", self.slurmctld.profiling.name)

        self._reconfigure()

    @leader
    @block_unless(slurmctld_installed)
    def _on_influxdb_unavailable(self, _: InfluxDBUnavailableEvent) -> None:
        """Clear the `acct_gather.conf` options on departed relation."""
        logger.info("`influxdb` database is no longer available. disabling job profiling")

        logger.info("deleting `%s` configuration", self.slurmctld.acct_gather.name)
        self.slurmctld.acct_gather.delete()
        logger.info("`%s` configuration deleted successfully", self.slurmctld.acct_gather.name)

        logger.info("clearing `%s` configuration", self.slurmctld.profiling.name)
        with self.slurmctld.profiling.edit() as profiling:
            del profiling.acct_gather_profile_type
            del profiling.acct_gather_interconnect_type
            del profiling.accounting_storage_tres
            del profiling.acct_gather_node_freq
            del profiling.job_acct_gather_frequency
            del profiling.job_acct_gather_type

        logger.info("`%s` configuration cleared successfully", self.slurmctld.profiling.name)
        self._reconfigure()

    @block_unless(slurmctld_installed)
    def _on_oci_runtime_ready(self, event: OCIRuntimeReadyEvent) -> None:
        """Handle when OCI runtime data is ready from a Slurm OCI runtime provider."""
        data = self.oci_runtime.get_oci_runtime_data(event.relation.id)

        logger.info("updating `%s` configuration", self.slurmctld.oci.name)
        logger.debug("`%s`:\n%s", self.slurmctld.oci.name, plog(data.ociconfig.dict()))
        self.slurmctld.oci.dump(data.ociconfig)
        logger.info("`%s` configuration updated successfully", self.slurmctld.oci.name)
        self._reconfigure()

    @block_unless(slurmctld_installed)
    def _on_oci_runtime_disconnected(self, _: OCIRuntimeDisconnectedEvent) -> None:
        """Handle when a Slurm OCI runtime is disconnected."""
        logger.info("oci runtime has been disconnected. disabling oci support")

        logger.info("deleting `%s` configuration", self.slurmctld.oci.name)
        self.slurmctld.oci.delete()
        logger.info("`%s` configuration deleted successfully", self.slurmctld.oci.name)

        self._reconfigure()

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
        elif state == "idle" and reason:
            event.log(
                "Warning: The 'idle' state does not require a reason to be set. "
                f"Not updating to node(s) {nodes} 'reason' field to '{reason}'."
            )

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

    @refresh
    @wait_unless(database_ready)
    @block_unless(slurmctld_installed)
    def _on_smtp_relation_created(self, event: ops.RelationCreatedEvent) -> None:
        """Set up SMTP relation."""
        message = "installing slurm-mail package"
        logger.info(message)
        self.unit.status = ops.MaintenanceStatus(message.capitalize())

        try:
            mail.install()
        except mail.MailOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to install slurm-mail package. See `juju debug-log` for details"
                )
            )

    @refresh
    @wait_unless(database_ready)
    @block_unless(slurmctld_installed)
    def _on_smtp_data_available(self, event: SmtpDataAvailableEvent) -> None:
        """Apply new or changed SMTP data."""
        message = "configuring slurm-mail"
        logger.info(message)
        self.unit.status = ops.MaintenanceStatus(message.capitalize())

        password = None
        if event.password_id:
            secret = self.model.get_secret(id=event.password_id)
            password = secret.get_content(refresh=True).get("password")

        use_tls = "no"
        if event.transport_security in ("starttls", "tls"):
            use_tls = "yes"

        try:
            with mail.configure() as config:
                config.server = event.host
                config.port = event.port
                config.use_tls = use_tls
                config.user = event.user
                config.password = password
                config.from_name = self.configmgr.email_from_name
        except mail.MailOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to configure slurm-mail. See `juju debug-log` for details"
                )
            )

        if self.unit.is_leader():
            with self.slurmctld.config.edit() as config:
                config.mail_prog = str(MAILPROG_PATH)

        self._reconfigure()

    def _on_smtp_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle SMTP relation departing."""
        if event.departing_unit == self.unit:
            self._stored.unit_departing = True

    @refresh
    @block_unless(slurmctld_installed)
    def _on_smtp_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Clean up on SMTP relation breaking."""
        if self._stored.unit_departing:
            # Do not remove config if broken event is due to slurmctld being scaled down rather than
            # the relation or application being removed
            return

        message = "uninstalling slurm-mail package"
        logger.info(message)
        self.unit.status = ops.MaintenanceStatus(message.capitalize())

        if self.unit.is_leader():
            with self.slurmctld.config.edit() as config:
                if config.mail_prog:
                    del config.mail_prog

        try:
            mail.uninstall()
        except mail.MailOpsError as e:
            logger.error(e.message)
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to uninstall slurm-mail package. See `juju debug-log` for details"
                )
            )

        self._reconfigure()

    def _get_controllers(self) -> list[str]:
        """Get hostnames for all Slurm controllers."""
        # Read the current list of controllers from the slurm.conf file and compare with the
        # controllers currently in the peer relation.
        # File ordering must be preserved as it dictates which slurmctld instance is the primary and
        # which are backups.
        from_file = self.slurmctld.get_controllers()
        from_peer = self.slurmctld_peer.get_controllers()

        logger.debug(
            "controllers from slurm.conf: %s, from peer integration: %s", from_file, from_peer
        )

        # Controllers in the file but not the peer relation have departed.
        # Controllers in the peer relation but not the file are newly added.
        from_file_set = set(from_file)
        controllers = [c for c in from_file if c in from_peer] + [
            c for c in from_peer if c not in from_file_set
        ]

        logger.debug("current controllers: %s", controllers)
        return controllers

    def _reconfigure(self) -> None:
        """Reconfigure the `slurmctld` and update integration databags.

        Notes:
            - In a `slurmctld` high availability setup, all `slurmctld` services across all
              `slurmctld` units in the cluster are restarted by this function. This ensures all
              `slurm.conf` changes are picked up, including those not re-read by an
              `scontrol reconfigure` command. If a restart is not done, removal of a controller
              will result in a malfunctioning cluster as `SlurmctldHost` lines are not
              re-read and an availability event may cause a failover attempt to
              a nonexistent backup.

        Raises:
            StopCharm: Raised if an error occurs when reconfiguring the `slurmctld` service.
        """
        if not slurmctld_ready(self):
            return

        # This must occur before `scontrol reconfigure` in case the primary `slurmctld` has been
        # removed and this unit is a backup being promoted to the new primary.
        #
        # If the `scontrol reconfigure` is performed first in this situation, it fails with:
        #   '['scontrol', 'reconfigure']' failed with exit code 1. reason: slurm_reconfigure error:
        #   Slurm backup controller in standby mode
        try:
            self.slurmctld.reconfigure(restart=True)
        except SlurmOpsError as e:
            logger.error(e.message)
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to restart `slurmctld.service`. See `juju debug-log` for details"
                )
            )
        self.slurmctld_peer.signal_slurmctld_restart()

        try:
            self.slurmctld.reconfigure()
        except SlurmOpsError as e:
            logger.error(e.message)
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to apply new Slurm configuration. See `juju debug-log` for details"
                )
            )

        if self.slurmrestd.is_joined():
            self.slurmrestd.set_controller_data(
                ControllerData(
                    slurmconfig={
                        "slurm.conf": self.slurmctld.config.load(),
                        **{k: v.load() for k, v in self.slurmctld.config.includes.items()},
                    }
                )
            )

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
            - This function must only be called by a hook that calls the `_reconfigure`
              method to ensure slurmrestd is also updated with the new Slurm configuration.
        """
        new_controllers = self._get_controllers()
        with self.slurmctld.config.edit() as config:
            config.slurmctld_host = new_controllers

        # sackd and slurmd require a list of endpoints (host:port), rather than just hostnames
        new_endpoints = [f"{c}:{SLURMCTLD_PORT}" for c in new_controllers]
        self._merge_controller_data(self.sackd, new_endpoints)
        self._merge_controller_data(self.slurmd, new_endpoints)


if __name__ == "__main__":  # noqa
    ops.main(SlurmctldCharm)
