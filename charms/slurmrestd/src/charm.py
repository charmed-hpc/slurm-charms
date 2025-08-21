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

"""Charmed operator for `slurmrestd`, Slurm's REST API service."""

import logging

import ops
from constants import SLURMRESTD_INTEGRATION_NAME, SLURMRESTD_PORT
from hpc_libs.interfaces import (
    SlurmctldDisconnectedEvent,
    SlurmctldReadyEvent,
    SlurmrestdProvider,
    block_when,
    controller_not_ready,
    wait_when,
)
from hpc_libs.utils import StopCharm, refresh
from slurm_ops import SlurmOpsError, SlurmrestdManager
from state import check_slurmrestd, slurmrestd_not_installed

logger = logging.getLogger(__name__)
refresh = refresh(check=check_slurmrestd)


class SlurmrestdCharm(ops.CharmBase):
    """Charmed operator for `slurmrestd`, Slurm's REST API service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmrestd = SlurmrestdManager(snap=False)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.update_status, self._on_update_status)

        self.slurmctld = SlurmrestdProvider(self, SLURMRESTD_INTEGRATION_NAME)
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
        """Install `slurmrestd` after charm is deployed on unit.

        Notes
            - The `slurmrestd` service is enabled by default after being installed using `apt`,
              so the service is stopped and disabled. The service is re-enabled after being
              integrated with a `slurmctld` application.
        """
        self.unit.status = ops.MaintenanceStatus("Installing `slurmrestd`")
        try:
            self.slurmrestd.install()
            self.slurmrestd.service.stop()
            self.slurmrestd.service.disable()
            self.unit.set_workload_version(self.slurmrestd.version())
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to install `slurmrestd`. See `juju debug-log` for details."
                )
            )

        self.unit.open_port("tcp", SLURMRESTD_PORT)

    @refresh
    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Check status of the `slurmrestd` application/unit."""

    @refresh
    @wait_when(controller_not_ready)
    @block_when(slurmrestd_not_installed)
    def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
        """Handle when controller data is ready from `slurmctld`."""
        data = self.slurmctld.get_controller_data(event.relation.id)

        try:
            self.slurmrestd.key.set(data.auth_key)
            for name, config in data.slurmconfig.items():
                self.slurmrestd.config.includes[name].dump(config)
            self.slurmrestd.service.enable()
            self.slurmrestd.service.restart()
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus("Failed to start `slurmrestd`. See `juju debug-log` for details")
            )

    @refresh
    def _on_slurmctld_disconnected(self, event: SlurmctldDisconnectedEvent) -> None:
        """Handle when unit is disconnected from `slurmctld`."""
        try:
            self.slurmrestd.service.disable()
            self.slurmrestd.service.stop()
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus("Failed to stop `slurmrestd`. See `juju debug-log` for details")
            )


if __name__ == "__main__":
    ops.main(SlurmrestdCharm)
