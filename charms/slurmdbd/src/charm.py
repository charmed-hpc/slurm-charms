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

"""Charmed operator for `slurmdbd`, Slurm's database service."""

import logging
from urllib.parse import urlparse

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseCreatedEvent, DatabaseRequires
from config import ConfigManager
from constants import (
    DATABASE_INTEGRATION_NAME,
    PEER_INTEGRATION_NAME,
    SLURM_ACCT_DATABASE_NAME,
    SLURMDBD_INTEGRATION_NAME,
    SLURMDBD_PORT,
)
from hpc_libs.interfaces import (
    DatabaseData,
    SlurmctldReadyEvent,
    SlurmdbdProvider,
    block_unless,
    controller_ready,
    wait_unless,
)
from hpc_libs.utils import StopCharm, get_ingress_address, leader, refresh
from pydantic import ValidationError
from slurm_ops import SlurmdbdManager, SlurmOpsError
from slurmutils import SlurmdbdConfig
from state import check_slurmdbd, slurmdbd_installed, slurmdbd_ready

logger = logging.getLogger(__name__)

refresh = refresh(hook=check_slurmdbd)
refresh.__doc__ = """Refresh status of the `slurmdbd` unit after an event handler completes."""


class SlurmdbdCharm(ops.CharmBase):
    """Charmed operator for `slurmdbd`, Slurm's database service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmdbd = SlurmdbdManager(snap=False)
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
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.update_status, self._on_update_status)

        self.slurmctld = SlurmdbdProvider(self, SLURMDBD_INTEGRATION_NAME)
        framework.observe(self.slurmctld.on.slurmctld_ready, self._on_slurmctld_ready)

        self.database = DatabaseRequires(
            self,
            relation_name=DATABASE_INTEGRATION_NAME,
            database_name=SLURM_ACCT_DATABASE_NAME,
        )
        framework.observe(self.database.on.database_created, self._on_database_created)

    @refresh
    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install `slurmdbd` after charm is deployed on the unit.

        Notes:
            - The `slurmdbd` service is enabled by default after being installed using `apt`,
              so the service is stopped and disabled. The service is re-enabled after being
              integrated with a `slurmctld` application and backend database provider.
        """
        if not self.unit.is_leader():
            raise StopCharm(
                ops.BlockedStatus(
                    "`slurmdbd` high-availability is not supported. Scale down application"
                )
            )

        self.unit.status = ops.MaintenanceStatus("Installing `slurmdbd`")
        try:
            self.slurmdbd.install()
            self.slurmdbd.service.stop()
            self.slurmdbd.service.disable()
            self.unit.set_workload_version(self.slurmdbd.version())
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to install `slurmdbd`. See `juju debug-log` for details."
                )
            )

        self.unit.open_port("tcp", SLURMDBD_PORT)

    @leader
    @refresh
    def _on_config_changed(self, _: ops.ConfigChangedEvent) -> None:
        """Update the `slurmdbd` charm's configuration."""
        # `slurmdbd.conf` must be updated here since the ingress address is not available
        # in the `install` hook.
        with self.slurmdbd.config.edit() as config:
            config.auth_alt_parameters = {"jwt_key": f"{self.slurmdbd.jwt.path}"}
            config.auth_alt_types = ["auth/jwt"]
            config.auth_type = "auth/slurm"
            config.dbd_addr = get_ingress_address(self, PEER_INTEGRATION_NAME)
            config.dbd_host = self.slurmdbd.hostname
            config.dbd_port = SLURMDBD_PORT
            config.log_file = "/var/log/slurm/slurmdbd.log"
            config.pid_file = "/var/run/slurmdbd/slurmdbd.pid"
            config.plugin_dir = ["/usr/lib/x86_64-linux-gnu/slurm-wlm"]
            config.slurm_user = self.slurmdbd.user
            config.storage_type = "accounting_storage/mysql"

        self.slurmdbd.overrides.dump(self.configmgr.slurmdbd_conf_parameters)

        self._reconfigure()

    @leader
    @refresh
    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Check status of the `slurmdbd` application unit."""

    @leader
    @refresh
    @wait_unless(controller_ready)
    @block_unless(slurmdbd_installed)
    def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
        """Handle when controller data is ready from `slurmctld`."""
        data = self.slurmctld.get_controller_data(event.relation.id)

        self.slurmdbd.key.set(data.auth_key)
        self.slurmdbd.jwt.set(data.jwt_key)
        self._reconfigure()

    @leader
    @refresh
    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Process the `DatabaseCreatedEvent` and update the database parameters.

        Raises:
            ValueError: When the database endpoints are invalid (for example, empty).

        Notes:
            - Updates the database parameters for the slurmdbd configuration based up on the
              `DatabaseCreatedEvent`. The type of update depends on the endpoints provided in
              the `DatabaseCreatedEvent`.
            - If the endpoints provided are file paths to unix sockets then the
              /etc/default/slurmdbd file will be updated to tell the MySQL client to
              use the socket.
            - If the endpoints provided are Address:Port tuples, then the address and port are
              updated as the database parameters in the slurmdbd.conf configuration file.
        """
        logger.debug("configuring new backend database for slurmdbd")

        config = SlurmdbdConfig()
        config.storage_user = event.username
        config.storage_pass = event.password
        config.storage_loc = SLURM_ACCT_DATABASE_NAME

        socket_endpoints = []
        tcp_endpoints = []
        if not event.endpoints:
            # This is 100% an error condition that the charm doesn't know how to handle
            # and is an unexpected condition. Raise an error here to fail the hook in
            # a bad way. The event isn't deferred as this is a situation that requires
            # a human to look at and resolve the proper next steps. Reprocessing the
            # deferred event will only result in continual errors.
            logger.error("no endpoints provided: %s", event.endpoints)
            self.unit.status = ops.BlockedStatus("No database endpoints provided")
            raise ValueError(f"no endpoints provided: {event.endpoints}")

        for endpoint in [ep.strip() for ep in event.endpoints.split(",")]:
            if not endpoint:
                continue

            if endpoint.startswith("file://"):
                socket_endpoints.append(endpoint)
            else:
                tcp_endpoints.append(endpoint)

        if socket_endpoints:
            # Socket endpoints will be preferred. This is the case when the mysql
            # configuration is using the mysql-router on the local node.
            logger.debug("updating environment for mysql socket access")
            if len(socket_endpoints) > 1:
                logger.warning(
                    "%s socket endpoints are specified, but only first one will be used.",
                    len(socket_endpoints),
                )
            # Make sure to strip the file:// off the front of the first endpoint
            # otherwise slurmdbd will not be able to connect to the database
            self.slurmdbd.mysql_unix_port = urlparse(socket_endpoints[0]).path
        elif tcp_endpoints:
            # This must be using TCP endpoint and the connection information will
            # be host_address:port. Only one remote mysql service will be configured
            # in this case.
            logger.debug("using tcp endpoints specified in the relation")
            if len(tcp_endpoints) > 1:
                logger.warning(
                    "%s tcp endpoints are specified, but only the first one will be used",
                    len(tcp_endpoints),
                )
            addr, port = tcp_endpoints[0].rsplit(":", 1)
            # Check IPv6 and strip any brackets
            if addr.startswith("[") and addr.endswith("]"):
                addr = addr[1:-1]

            config.storage_host = addr
            config.storage_port = int(port)

            # Make sure that the MYSQL_UNIX_PORT is removed from the env file.
            del self.slurmdbd.mysql_unix_port
        else:
            # This is 100% an error condition that the charm doesn't know how to handle
            # and is an unexpected condition. This happens when there are commas but no
            # usable data in the endpoints.
            logger.error("no endpoints provided: %s", event.endpoints)
            self.unit.status = ops.BlockedStatus("No database endpoints provided")
            raise ValueError(f"no endpoints provided: {event.endpoints}")

        self.slurmdbd.storage.dump(config)
        self._reconfigure()

    def _reconfigure(self) -> None:
        """Reconfigure the `slurmdbd` service and update `slurmctld` integration databag.

        Raises:
            StopCharm: Raised if an error occurs when reconfiguring the `slurmdbd` service.
        """
        if not slurmdbd_ready(self):
            return

        try:
            self.slurmdbd.reconfigure()
        except SlurmOpsError as e:
            logger.error(e.message)
            raise StopCharm(
                ops.BlockedStatus(
                    "Failed to apply updated `slurmdbd` configuration. "
                    "See `juju debug-log` for details"
                )
            )

        self.slurmctld.set_database_data(DatabaseData(hostname=self.slurmdbd.hostname))


if __name__ == "__main__":
    ops.main(SlurmdbdCharm)
