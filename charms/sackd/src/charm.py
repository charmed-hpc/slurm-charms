#!/usr/bin/env python3
# Copyright 2024-2026 Canonical Ltd.
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
from charmed_hpc_libs.errors import SnapError, SystemdError
from charmed_hpc_libs.ops import StopCharm, block_unless, refresh, systemctl, wait_unless
from charmed_slurm_sackd_interface import (
    AUTH_KEY_LABEL,
    SackdProvider,
    SlurmctldDisconnectedEvent,
    SlurmctldReadyEvent,
    controller_ready,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from constants import PROMETHEUS_SCRAPE_INTEGRATION_NAME, SACKD_INTEGRATION_NAME, SACKD_PORT
from slurm_ops import (
    NODE_EXPORTER_COLLECTORS,
    NODE_EXPORTER_PLUGS,
    NODE_EXPORTER_PORT,
    NODE_EXPORTER_SCRAPE_CONFIG,
    SackdManager,
    SlurmOpsError,
)
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
        framework.observe(self.on.secret_changed, self._on_secret_changed)

        self.slurmctld = SackdProvider(self, SACKD_INTEGRATION_NAME)
        framework.observe(
            self.slurmctld.on.slurmctld_ready,
            self._on_slurmctld_ready,
        )
        framework.observe(
            self.slurmctld.on.slurmctld_disconnected,
            self._on_slurmctld_disconnected,
        )

        self.metrics_endpoint = MetricsEndpointProvider(
            self,
            PROMETHEUS_SCRAPE_INTEGRATION_NAME,
            alert_rules_path="./src/cos/alert_rules/prometheus",
            jobs=[NODE_EXPORTER_SCRAPE_CONFIG]
        )

    @refresh
    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install `sackd` after charm is deployed on unit.

        Notes:
            - The `sackd` service is enabled by default after being installed using `apt`,
              so the service is stopped and disabled. The service is re-enabled after being
              integrated with a `slurmctld` application.
        """
        try:
            self.unit.status = ops.MaintenanceStatus("Installing `sackd`")
            self.sackd.install()
            self.sackd.service.stop()
            self.sackd.service.disable()
            self.unit.open_port("tcp", SACKD_PORT)
            self.unit.set_workload_version(self.sackd.version())

            self.unit.status = ops.MaintenanceStatus("Installing `node-exporter`")
            self.sackd.node_exporter.install()
            for plug in NODE_EXPORTER_PLUGS:
                self.sackd.node_exporter.connect(plug)
            self.sackd.node_exporter.set_web_listen_address(f":{NODE_EXPORTER_PORT}")
            self.sackd.node_exporter.set_collectors(NODE_EXPORTER_COLLECTORS)
            self.sackd.node_exporter.service.enable()
        except (SlurmOpsError, SnapError) as e:
            error_message = {
                SlurmOpsError: "Failed to install `sackd`",
                SnapError: "Failed to install `node-exporter`",
            }

            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(f"{error_message[type(e)]}. See `juju debug-log` for details")
            )

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
            self.sackd.key.set({"key": data.auth_key, "keyid": data.auth_key_id})
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

    @refresh
    @block_unless(sackd_installed)
    def _on_secret_changed(self, event: ops.SecretChangedEvent) -> None:
        """Handle when a secret is changed."""
        if event.secret.label != AUTH_KEY_LABEL:
            logger.warning("secret with label '%s' changed. ignoring", event.secret.label)
            return

        try:
            content = event.secret.get_content(refresh=True)
            self.sackd.key.set(content)
        except (ops.SecretNotFoundError, ops.ModelError, ValueError) as e:
            logger.error("failed to retrieve auth key contents. reason:\n%s", e)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to retrieve Slurm authentication key. See `juju debug-log` for details"
                )
            )

        # Necessary to load new key from file into the service
        # TODO: replace with self.service.reload()
        try:
            systemctl("reload", "sackd.service")
        except SystemdError as e:
            logger.error("failed to reload sackd.service. reason:\n%s", e)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to reload `sackd` configuration. See `juju debug-log` for details"
                )
            )


if __name__ == "__main__":  # pragma: nocover
    ops.main(SackdCharm)
