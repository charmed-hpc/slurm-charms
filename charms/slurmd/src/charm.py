#!/usr/bin/env python3
# Copyright 2025-2026 Vantage Compute Corporation
# Copyright 2020-2024 Omnivector, LLC.
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

"""Charmed operator for `slurmd`, Slurm's compute node service."""

import logging

import gpu
import ops
import rdma
from charmed_hpc_libs.errors import SnapError, SystemdError
from charmed_hpc_libs.ops import StopCharm, block_unless, refresh, wait_unless
from charmed_slurm_slurmd_interface import (
    AUTH_KEY_LABEL,
    ComputeData,
    SlurmctldConnectedEvent,
    SlurmctldDisconnectedEvent,
    SlurmctldReadyEvent,
    SlurmdProvider,
    controller_ready,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from config import ConfigManager
from constants import PROMETHEUS_SCRAPE_INTEGRATION_NAME, SLURMD_INTEGRATION_NAME, SLURMD_PORT
from pydantic import ValidationError
from slurm_ops import (
    NODE_EXPORTER_COLLECTORS,
    NODE_EXPORTER_PLUGS,
    NODE_EXPORTER_PORT,
    NODE_EXPORTER_SCRAPE_CONFIG,
    SlurmdManager,
    SlurmOpsError,
)
from slurmutils import ModelError, Node
from state import check_slurmd, reboot_if_required, slurmd_installed

logger = logging.getLogger(__name__)
refresh = refresh(hook=check_slurmd)
refresh.__doc__ = """Refresh status of the `slurmd` unit after an event handler completes."""


class SlurmdCharm(ops.CharmBase):
    """Charmed operator for `slurmd`, Slurm's compute node service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmd = SlurmdManager(self.app.name, snap=False)
        try:
            self.configmgr = self.load_config(ConfigManager, partition_name=self.app.name)
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
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on.secret_changed, self._on_secret_changed)
        framework.observe(self.on.set_node_config_action, self._on_set_node_config_action)

        self.slurmctld = SlurmdProvider(self, SLURMD_INTEGRATION_NAME)
        framework.observe(
            self.slurmctld.on.slurmctld_connected,
            self._on_slurmctld_connected,
        )
        framework.observe(
            self.slurmctld.on.slurmctld_ready,
            self._on_slurmctld_ready,
        )
        framework.observe(
            self.slurmctld.on.slurmctld_disconnected,
            self._on_slurmctld_disconnected,
        )

        # FIXME: Only enable `dcgm` scrape job if GPU is present on the node.
        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            PROMETHEUS_SCRAPE_INTEGRATION_NAME,
            jobs=[NODE_EXPORTER_SCRAPE_CONFIG, gpu.DCGM_EXPORTER_SCRAPE_CONFIG],
        )

    @refresh
    def _on_install(self, event: ops.InstallEvent) -> None:
        """Provision the compute node after charm is deployed on unit.

        Notes:
            - The machine will be rebooted before the installation hook runs if the base image
              has been upgraded by Juju and a reboot is required. The installation hook will be
              restarted after the reboot completes. This preemptive reboot is performed to
              prevent issues such as device drivers or kernel modules being installed for a
              running kernel pending replacement by a kernel version on reboot.
        """
        reboot_if_required(self, now=True)

        try:
            self.unit.status = ops.MaintenanceStatus("Installing `slurmd`")
            self.slurmd.install()
            self.slurmd.service.stop()
            self.slurmd.service.disable()
            self.slurmd.conf = self.slurmd.build_node()
            self.slurmd.dynamic = True
            self.slurmd.name = self.unit.name.replace("/", "-")
            self.unit.open_port("tcp", SLURMD_PORT)
            self.unit.set_workload_version(self.slurmd.version())

            self.unit.status = ops.MaintenanceStatus("Installing GPU drivers")
            gpu_enabled = gpu.autoinstall()
            if gpu_enabled:
                self.unit.status = ops.MaintenanceStatus("Successfully installed GPU drivers")
            else:
                self.unit.status = ops.MaintenanceStatus(
                    "No GPUs detected. Skipping driver installation"
                )

            self.unit.status = ops.MaintenanceStatus("Installing RDMA drivers")
            rdma.install()

            self.unit.status = ops.MaintenanceStatus("Installing `node-exporter`")
            self.slurmd.node_exporter.install()
            for plug in NODE_EXPORTER_PLUGS:
                self.slurmd.node_exporter.connect(plug)
            self.slurmd.node_exporter.set_web_listen_address(f":{NODE_EXPORTER_PORT}")
            self.slurmd.node_exporter.set_collectors(NODE_EXPORTER_COLLECTORS)
            self.slurmd.node_exporter.service.enable()
        except (SlurmOpsError, gpu.GPUOpsError, rdma.RDMAOpsError, SnapError) as e:
            # FIXME: Investigate how to provide more granular status messages
            #   such as when it's the `dcgm-exporter` snap that fails to install
            #   and not the Nvidia drivers.
            error_message = {
                SlurmOpsError: "Failed to install `slurmd`",
                gpu.GPUOpsError: "Failed to install GPU drivers",
                rdma.RDMAOpsError: "Failed to install RDMA drivers",
                SnapError: "Failed to install `node-exporter`",
            }

            event.defer()
            logger.error(e.message)
            raise StopCharm(
                ops.BlockedStatus(f"{error_message[type(e)]}. See `juju debug-log` for details")
            )

        reboot_if_required(self)

    @refresh
    def _on_config_changed(self, _: ops.ConfigChangedEvent) -> None:
        """Update the `slurmd` application's configuration."""
        self.slurmctld.set_compute_data(ComputeData(partition=self.configmgr.partition_config))

    @refresh
    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Handle update status."""

    @refresh
    @block_unless(slurmd_installed)
    def _on_slurmctld_connected(self, event: SlurmctldConnectedEvent) -> None:
        """Handle when the `slurmd` application is connected to `slurmctld`."""
        self.slurmctld.set_compute_data(
            ComputeData(partition=self.configmgr.partition_config),
            integration_id=event.relation.id,
        )

    @refresh
    @wait_unless(controller_ready)
    @block_unless(slurmd_installed)
    def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
        """Handle when controller data is ready from the `slurmctld` application."""
        data = self.slurmctld.get_controller_data(event.relation.id)

        self.slurmd.key.set({"key": data.auth_key, "keyid": data.auth_key_id})
        self.slurmd.conf_server = data.controllers

        # Set default state and reason if this compute node is being added to a Slurm cluster.
        params = {}
        if not self.slurmd.exists():
            params = {
                "state": self.configmgr.default_node_state,
                "reason": self.configmgr.default_node_reason,
            }

        try:
            self.slurmd.reconfigure(**params)
        except SlurmOpsError as e:
            logger.error(e.message)
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to apply updated `slurmd` configuration. "
                    "See `juju debug-log` for details"
                )
            )

    @refresh
    @block_unless(slurmd_installed)
    def _on_slurmctld_disconnected(self, event: SlurmctldDisconnectedEvent) -> None:
        """Handle when the unit is disconnected from `slurmctld`."""
        try:
            self.slurmd.delete()
            self.slurmd.service.stop()
            self.slurmd.service.disable()
            del self.slurmd.conf_server
        except (SlurmOpsError, SystemdError) as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus("Failed to stop `slurmd`. See `juju debug-log` for details")
            )

    @refresh
    @block_unless(slurmd_installed)
    def _on_secret_changed(self, event: ops.SecretChangedEvent) -> None:
        """Handle when a secret is changed."""
        if event.secret.label != AUTH_KEY_LABEL:
            logger.warning("secret with label '%s' changed. ignoring", event.secret.label)
            return

        try:
            content = event.secret.get_content(refresh=True)
            self.slurmd.key.set(content)
        except (ops.SecretNotFoundError, ops.ModelError, ValueError) as e:
            logger.error("failed to retrieve auth key contents. reason:\n%s", e)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to retrieve Slurm authentication key. See `juju debug-log` for details"
                )
            )

        # Necessary to load new key from file into the service
        # FIXME: slurmd reloading is currently broken. Service restart is used as a workaround but
        # this breaks zero-downtime key rotation. This must be replaced with a reload
        # See: https://github.com/charmed-hpc/slurm-charms/issues/204
        self.slurmd.service.restart()

    @refresh
    def _on_set_node_config_action(self, event: ops.ActionEvent) -> None:
        """Handle when the `set-node-config` action is run."""
        try:
            custom = Node.from_str(event.params["parameters"])
        except (ModelError, ValueError) as e:
            event.fail(
                f"Validation for node configuration parameters '{event.params['parameters']}'"
                f" failed. Reason:\n{e.args[0]}"
            )
            event.set_results({"accepted": False})
            return

        if any(
            (
                custom.node_name is not None,
                custom.node_addr is not None,
                custom.node_hostname is not None,
                custom.state is not None,
                custom.reason is not None,
                custom.port is not None,
            )
        ):
            event.fail(
                f"Cannot apply node configuration parameters '{event.params['parameters']}'."
                f" Reason: Overrides charm-managed configuration parameter."
            )
            event.set_results({"accepted": False})
            return

        if event.params["reset"]:
            self.slurmd.conf = self.slurmd.build_node()

        config = self.slurmd.conf
        config.update(custom)
        self.slurmd.conf = config

        if self.slurmd.exists():
            try:
                info = self.slurmd.show_node()
                # Index '0' contains the desired state information.
                # The value of index '1' is "DYNAMIC_NORM" to show that this node is dynamic.
                state = info["state"][0].lower()
                reason = info["reason"]

                # Node must be deleted and reregistered if changing hardware configuration like
                # `RealMemory` or `MemSpecLimit`.
                self.slurmd.delete()
                self.slurmd.reconfigure(state=state, reason=reason)
            except SlurmOpsError as e:
                logger.error(e.message)
                event.fail(
                    "Failed to apply node configuration parameters. "
                    "See `juju debug-log` for further details."
                )
                event.set_results({"accepted": False})
                return

        event.set_results({"accepted": True})


if __name__ == "__main__":  # pragma: nocover
    ops.main(SlurmdCharm)
