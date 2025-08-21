#!/usr/bin/env python3
# Copyright 2025 Vantage Compute Corporation
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
from typing import cast

import gpu
import nhc
import ops
import rdma
from config import State, get_partition, reboot_if_required, reconfigure, set_partition
from constants import SLURMD_INTEGRATION_NAME, SLURMD_PORT
from hpc_libs.interfaces import (
    SlurmctldConnectedEvent,
    SlurmctldDisconnectedEvent,
    SlurmctldReadyEvent,
    SlurmdProvider,
    block_when,
    controller_not_ready,
    wait_when,
)
from hpc_libs.utils import StopCharm, refresh
from slurm_ops import SlurmdManager, SlurmOpsError, scontrol
from slurmutils import ModelError, Node
from state import check_slurmd, slurmd_not_installed

from charms.grafana_agent.v0.cos_agent import COSAgentProvider

logger = logging.getLogger(__name__)
refresh = refresh(check=check_slurmd)


class SlurmdCharm(ops.CharmBase):
    """Charmed operator for `slurmd`, Slurm's compute node service."""

    stored = ops.StoredState()
    service_needs_restart: bool = False

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmd = SlurmdManager(snap=False)
        self.stored.set_default(
            default_state=State.DOWN.value,
            default_reason="New node.",
            custom_node_config={},
            custom_nhc_config="",
            custom_partition_config="",
        )
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on.node_configured_action, self._on_node_configured_action)
        framework.observe(self.on.node_config_action, self._on_node_config_action)
        framework.observe(self.on.show_nhc_config_action, self._on_show_nhc_config_action)

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

        self._grafana_agent = COSAgentProvider(self)

    @refresh
    def _on_install(self, event: ops.InstallEvent) -> None:
        """Provision the compute node after charm is deployed on unit.

        Notes:
            - The machine will be rebooted before the installation hook runs if the base image
              has been upgraded by Juju and a reboot is required. The installation hook will be
              restarted after the reboot completes. This preemptive reboot is performed to
              Prevents issues such as device drivers or kernel modules being installed for a
              running kernel pending replacement by a kernel version on reboot.
        """
        reboot_if_required(self, now=True)
        self.unit.status = ops.MaintenanceStatus("Provisioning compute node")

        try:
            self.unit.status = ops.MaintenanceStatus("Installing `slurmd`")
            self.slurmd.install()

            self.unit.status = ops.MaintenanceStatus("Installing `nhc`")
            nhc.install()

            self.unit.status = ops.MaintenanceStatus("Installing RDMA packages")
            rdma.install()

            self.unit.status = ops.MaintenanceStatus("Detecting if machine is GPU-equipped")
            gpu_enabled = gpu.autoinstall()
            if gpu_enabled:
                self.unit.status = ops.MaintenanceStatus("Successfully installed GPU drivers")
            else:
                self.unit.status = ops.MaintenanceStatus("No GPUs found. Continuing")

            self.slurmd.service.stop()
            self.slurmd.service.disable()
            self.slurmd.dynamic = True
            self.unit.set_workload_version(self.slurmd.version())

        except (SlurmOpsError, gpu.GPUOpsError) as e:
            logger.error(e.message)
            event.defer()

        self.unit.open_port("tcp", SLURMD_PORT)
        reboot_if_required(self)

    @refresh
    def _on_config_changed(self, _: ops.ConfigChangedEvent) -> None:
        """Update the `slurmd` application's configuration."""
        custom_nhc_config = cast(str, self.config.get("nhc-conf", ""))
        if custom_nhc_config != self.stored.custom_nhc_config:
            logger.info("updating `nhc.conf` on unit '%s'", self.unit.name)
            logger.debug("'%s' `nhc.conf`:\n%s", self.unit.name, custom_nhc_config)
            nhc.generate_config(custom_nhc_config)
            self.stored.custom_nhc_config = custom_nhc_config
            logger.info("`nhc.conf` successfully updated on unit '%s'", self.unit.name)

        if self.unit.is_leader():
            custom_partition_config = cast(str, self.config.get("partition-config", ""))
            if custom_partition_config != self.stored.custom_partition_config:
                try:
                    set_partition(self, get_partition(self))
                except SlurmOpsError as e:
                    logger.error(e)
                    raise StopCharm(
                        ops.BlockedStatus(
                            "Failed to update partition configuration. "
                            + "See `juju debug-log` for details"
                        )
                    )

                self.stored.custom_partition_config = custom_partition_config

    @refresh
    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Handle update status."""

    @refresh
    @block_when(slurmd_not_installed)
    def _on_slurmctld_connected(self, event: SlurmctldConnectedEvent) -> None:
        """Handle when the `slurmd` application is connected to `slurmctld`."""
        try:
            set_partition(self, get_partition(self))
        except SlurmOpsError as e:
            logger.error(e)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to update partition configuration. "
                    + "See `juju debug-log` for details"
                )
            )

    @refresh
    @reconfigure
    @wait_when(controller_not_ready)
    @block_when(slurmd_not_installed)
    def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
        """Handle when controller data is ready from the `slurmctld` application."""
        data = self.slurmctld.get_controller_data(event.relation.id)

        self.slurmd.key.set(data.auth_key)
        self.slurmd.conf_server = data.controllers
        nhc.generate_wrapper(data.nhc_args)
        self.service_needs_restart = True

    @refresh
    @block_when(slurmd_not_installed)
    def _on_slurmctld_disconnected(self, event: SlurmctldDisconnectedEvent) -> None:
        """Handle when the unit is disconnected from `slurmctld`."""
        try:
            scontrol("delete", f"nodename={self.slurmd.hostname}")
            self.slurmd.service.stop()
            self.slurmd.service.disable()
            del self.slurmd.conf_server
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus("Failed to stop `slurmd`. See `juju debug-log` for details")
            )

    def _on_node_configured_action(self, _: ops.ActionEvent) -> None:
        """Move node from 'down' to 'idle'."""
        self.stored.default_state = State.IDLE.value
        self.stored.default_reason = ""

        node = self.slurmd.conf
        del node.state
        self.slurmd.conf = node

        # Update the nodes state if it is already enlisted with `slurmctld`.
        try:
            scontrol("update", f"nodename={self.slurmd.hostname}", "state=idle")
        except SlurmOpsError:
            pass

        logger.debug("this node is not new anymore")

    @refresh
    @reconfigure
    def _on_node_config_action(self, event: ops.ActionEvent) -> None:
        """Get or set the user_supplied_node_config.

        Return the node config if the `node-config` parameter is not specified, otherwise
        parse, validate, and store the input of the `node-config` parameter in stored state.
        Lastly, update slurmctld if there are updates to the node config.
        """
        node = self.slurmd.conf
        custom = event.params.get("parameters", "")
        valid_config = False
        if custom:
            try:
                node.update(Node.from_str(custom))
                valid_config = True
            except (ModelError, ValueError) as e:
                logger.error(e)

            if valid_config:
                if (custom_node_config := node.dict()) != self.stored.custom_node_config:
                    self.stored.custom_node_config = custom_node_config
                    self.service_needs_restart = True

        event.set_results(
            {
                "node-parameters": str(node),
                "user-supplied-node-parameters-accepted": f"{valid_config}",
            },
        )

    def _on_show_nhc_config_action(self, event: ops.ActionEvent) -> None:
        """Show current nhc.conf."""
        try:
            event.set_results({"nhc.conf": nhc.get_config()})
        except FileNotFoundError:
            event.set_results({"nhc.conf": "/etc/nhc/nhc.conf not found."})


if __name__ == "__main__":  # pragma: nocover
    ops.main(SlurmdCharm)
