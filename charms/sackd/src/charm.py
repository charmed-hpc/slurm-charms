#!/usr/bin/env python3
# Copyright 2024-2025 Canonical Ltd.
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

"""Charmed operator for `sackd`, Slurm's authentication kiosk service."""

import logging

import ops
from constants import SACKD_INTEGRATION_NAME, SACKD_PORT
from hpc_libs.interfaces import (
    SackdProvider,
    SlurmctldDisconnectedEvent,
    SlurmctldReadyEvent,
    block_unless,
    controller_ready,
    wait_unless,
)
from hpc_libs.utils import StopCharm, refresh
from slurm_ops import SackdManager, SlurmOpsError
from state import check_sackd, sackd_installed

logger = logging.getLogger(__name__)
refresh = refresh(hook=check_sackd)
refresh.__doc__ = """Refresh the status of the `sackd` unit after an event handler completes."""


class SackdCharm(ops.CharmBase):
    """Charmed operator for `sackd`, Slurm's authentication kiosk service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.sackd = SackdManager(snap=False)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.update_status, self._on_update_status)

        self.slurmctld = SackdProvider(self, SACKD_INTEGRATION_NAME)
        framework.observe(
            self.slurmctld.on.slurmctld_ready,
            self._on_slurmctld_ready,
        )
        framework.observe(
            self.slurmctld.on.slurmctld_disconnected,
            self._on_slurmctld_disconnected,
        )

    @refresh
    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install `sackd` after charm is deployed on unit.

        Notes:
            - The `sackd` service is enabled by default after being installed using `apt`,
              so the service is stopped and disabled. The service is re-enabled after being
              integrated with a `slurmctld` application.
        """
        self.unit.status = ops.MaintenanceStatus("Installing `sackd`")
        try:
            self.sackd.install()
            self.sackd.service.stop()
            self.sackd.service.disable()
            self.unit.set_workload_version(self.sackd.version())
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus("Failed to install `sackd`. See `juju debug-log` for details")
            )

        self.unit.open_port("tcp", SACKD_PORT)

    @refresh
    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Check status of the `sackd` application/unit."""

    @refresh
    @wait_unless(controller_ready)
    @block_unless(sackd_installed)
    def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
        """Handle when controller data is ready from `slurmctld`."""
        data = self.slurmctld.get_controller_data(event.relation.id)

        try:
            self.sackd.key.set(data.auth_key)
            self.sackd.conf_server = data.controllers
            self.sackd.service.enable()
            self.sackd.service.restart()
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus("Failed to start `sackd`. See `juju debug-log` for details")
            )

    @refresh
    @block_unless(sackd_installed)
    def _on_slurmctld_disconnected(self, event: SlurmctldDisconnectedEvent) -> None:
        """Handle when unit is disconnected from `slurmctld`."""
        try:
            self.sackd.service.stop()
            self.sackd.service.disable()
            del self.sackd.conf_server
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus("Failed to stop `sackd`. See `juju debug-log` for details")
            )


if __name__ == "__main__":  # pragma: nocover
    ops.main(SackdCharm)
