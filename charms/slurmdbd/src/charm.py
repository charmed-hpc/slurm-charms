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

"""Charmed operator for `slurmdbd`, Slurm's database service."""

# pyright: reportAttributeAccessIssue=false

import logging
from typing import Any
from urllib.parse import urlparse

import ops
from config import (
    init_config,
    reconfigure_slurmdbd,
    update_overrides,
    update_storage,
)
from constants import (
    DATABASE_INTEGRATION_NAME,
    SLURM_ACCT_DATABASE_NAME,
    SLURMDBD_INTEGRATION_NAME,
    SLURMDBD_PORT,
)
from hpc_libs.interfaces import (
    SlurmctldReadyEvent,
    SlurmdbdProvider,
    block_unless,
    controller_ready,
    wait_unless,
)
from hpc_libs.utils import StopCharm, leader, reconfigure, refresh
from slurm_ops import SlurmdbdManager, SlurmOpsError
from state import check_slurmdbd, slurmdbd_installed

from charms.data_platform_libs.v0.data_interfaces import DatabaseCreatedEvent, DatabaseRequires
from charms.grafana_agent.v0.cos_agent import COSAgentProvider

logger = logging.getLogger(__name__)
#
reconfigure = reconfigure(hook=reconfigure_slurmdbd)
reconfigure.__doc__ = """Reconfigure the `slurmdbd` service after an event handler completes."""
refresh = refresh(hook=check_slurmdbd)
refresh.__doc__ = """Refresh status of the `slurmdbd` unit after an event handler completes."""


class SlurmdbdCharm(ops.CharmBase):
    """Charmed operator for `slurmdbd`, Slurm's database service."""

    stored = ops.StoredState()
    service_needs_restart: bool = False

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmdbd = SlurmdbdManager(snap=False)
        self.stored.set_default(
            database_info={},
            custom_slurmdbd_config={},
        )
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
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

        self._grafana_agent = COSAgentProvider(self)

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

    @refresh
    @reconfigure
    def _on_start(self, _: ops.StartEvent) -> None:
        """Write initial `slurmdbd.conf` file."""
        if not self.unit.is_leader():
            raise StopCharm(
                ops.BlockedStatus(
                    "`slurmdbd` high-availability is not supported. Scale down application"
                )
            )

        init_config(self)

    @leader
    @refresh
    @reconfigure
    def _on_config_changed(self, _: ops.ConfigChangedEvent) -> None:
        """Update the `slurmdbd` charm's configuration."""
        update_overrides(self)

    @leader
    @refresh
    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
        """Check status of the `slurmdbd` application unit."""

    @leader
    @refresh
    @reconfigure
    @wait_unless(controller_ready)
    @block_unless(slurmdbd_installed)
    def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
        """Handle when controller data is ready from `slurmctld`."""
        data = self.slurmctld.get_controller_data(event.relation.id)

        self.slurmdbd.key.set(data.auth_key)
        self.slurmdbd.jwt.set(data.jwt_key)

    @leader
    @refresh
    @reconfigure
    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Process the `DatabaseCreatedEvent` and update the database parameters.

        Raises:
            ValueError: When the database endpoints are invalid (e.g. empty).

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

        database_info: dict[str, Any] = {
            "storageuser": event.username,
            "storagepass": event.password,
            "storageloc": SLURM_ACCT_DATABASE_NAME,
        }

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
            database_info.update(
                {
                    "storagehost": addr,
                    "storageport": int(port),
                }
            )
            # Make sure that the MYSQL_UNIX_PORT is removed from the env file.
            del self.slurmdbd.mysql_unix_port
        else:
            # This is 100% an error condition that the charm doesn't know how to handle
            # and is an unexpected condition. This happens when there are commas but no
            # usable data in the endpoints.
            logger.error("no endpoints provided: %s", event.endpoints)
            self.unit.status = ops.BlockedStatus("No database endpoints provided")
            raise ValueError(f"no endpoints provided: {event.endpoints}")

        update_storage(self, database_info)


if __name__ == "__main__":
    ops.main(SlurmdbdCharm)
