#!/usr/bin/env python3
# Copyright 2020-2024 Omnivector, LLC.
# See LICENSE file for licensing details.

"""Slurmdbd Operator Charm."""

# pyright: reportAttributeAccessIssue=false

import logging
from time import sleep
from typing import Any, Union
from urllib.parse import urlparse

from constants import CHARM_MAINTAINED_PARAMETERS, PEER_RELATION, SLURM_ACCT_DB, SLURMDBD_PORT
from exceptions import IngressAddressUnavailableError
from interface_slurmctld import Slurmctld, SlurmctldAvailableEvent, SlurmctldUnavailableEvent
from ops import (
    ActiveStatus,
    BlockedStatus,
    CharmBase,
    ConfigChangedEvent,
    InstallEvent,
    ModelError,
    StoredState,
    UpdateStatusEvent,
    WaitingStatus,
    main,
)
from slurm_ops import SlurmdbdManager, SlurmOpsError
from slurmutils import SlurmdbdConfig

from charms.data_platform_libs.v0.data_interfaces import DatabaseCreatedEvent, DatabaseRequires
from charms.grafana_agent.v0.cos_agent import COSAgentProvider

logger = logging.getLogger(__name__)


class SlurmdbdCharm(CharmBase):
    """Slurmdbd Charm."""

    _stored = StoredState()

    def __init__(self, *args, **kwargs) -> None:
        """Set the default class attributes."""
        super().__init__(*args, **kwargs)

        self._stored.set_default(
            slurm_installed=False,
            db_info={},
            user_slurmdbd_params={},
            user_slurmdbd_params_str=str(),
        )

        self._slurmdbd = SlurmdbdManager(snap=False)
        self._slurmctld = Slurmctld(self, "slurmctld")
        self._db = DatabaseRequires(self, relation_name="database", database_name=SLURM_ACCT_DB)
        self._grafana_agent = COSAgentProvider(self)

        event_handler_bindings = {
            self.on.install: self._on_install,
            self.on.update_status: self._on_update_status,
            self.on.config_changed: self._on_config_changed,
            self._db.on.database_created: self._on_database_created,
            self._slurmctld.on.slurmctld_available: self._on_slurmctld_available,
            self._slurmctld.on.slurmctld_unavailable: self._on_slurmctld_unavailable,
        }
        for event, handler in event_handler_bindings.items():
            self.framework.observe(event, handler)

    def _on_install(self, event: InstallEvent) -> None:
        """Perform installation operations for slurmdbd."""
        self.unit.status = WaitingStatus("installing slurmdbd")
        try:
            if self.unit.is_leader():
                self._slurmdbd.install()
                self.unit.set_workload_version(self._slurmdbd.version())
                self._slurmdbd.service.enable()

                self._stored.slurm_installed = True
            else:
                logger.warning(
                    "slurmdbd high-availability is not supported yet. please scale down application."
                )
                event.defer()
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()

        self.unit.open_port("tcp", SLURMDBD_PORT)
        self._check_status()

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Process configuration changes."""
        write_config_and_restart = False

        if (user_slurmdbd_params_str := self.config.get("slurmdbd-conf-parameters")) is not None:
            user_slurmdbd_params_str = str(user_slurmdbd_params_str)
            if user_slurmdbd_params_str != self._stored.user_slurmdbd_params_str:
                logger.debug("## User supplied parameters changed, saving to charm state.")
                self._stored.user_slurmdbd_params_str = user_slurmdbd_params_str

                try:
                    config = SlurmdbdConfig.from_str(user_slurmdbd_params_str)
                    self._stored.user_slurmdbd_params = config.dict()
                    write_config_and_restart = True
                except (ModelError, ValueError) as e:
                    logger.error("could not parse user supplied parameters. reason: %s", e.message)
                    raise e

        if write_config_and_restart is True:
            self._write_config_and_restart_slurmdbd(event)

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handle update status."""
        self._check_status()

    def _on_slurmctld_available(self, event: SlurmctldAvailableEvent) -> None:
        """Retrieve and configure the jwt_rsa and auth_key when slurmctld_available."""
        if self._stored.slurm_installed is not True:
            event.defer()
            return

        if (jwt := event.jwt_rsa) is not None:
            self._slurmdbd.jwt.set(jwt)

        if (auth_key := event.auth_key) is not None:
            self._slurmdbd.key.set(auth_key)

        # Don't try to write the config before the database has been created.
        # Otherwise, this will trigger a defer on this event, which we don't really need.
        if self._stored.db_info:
            self._write_config_and_restart_slurmdbd(event)

    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Process the DatabaseCreatedEvent and updates the database parameters.

        Updates the database parameters for the slurmdbd configuration based up on the
        DatabaseCreatedEvent. The type of update depends on the endpoints provided in
        the DatabaseCreatedEvent.

        If the endpoints provided are file paths to unix sockets
        then the /etc/default/slurmdbd file will be updated to tell the MySQL client to
        use the socket.

        If the endpoints provided are Address:Port tuples, then the address and port are
        updated as the database parameters in the slurmdbd.conf configuration file.

        Args:
            event (DatabaseCreatedEvent):
                Information passed by MySQL after the slurm_acct_db database has been created.

        Raises:
            ValueError:
                When the database endpoints are invalid (e.g. empty).
        """
        logger.debug("Configuring new backend database for slurmdbd.")

        socket_endpoints = []
        tcp_endpoints = []
        if not event.endpoints:
            # This is 100% an error condition that the charm doesn't know how to handle
            # and is an unexpected condition. Raise an error here to fail the hook in
            # a bad way. The event isn't deferred as this is a situation that requires
            # a human to look at and resolve the proper next steps. Reprocessing the
            # deferred event will only result in continual errors.
            logger.error(f"No endpoints provided: {event.endpoints}")
            self.unit.status = BlockedStatus("No database endpoints provided")
            raise ValueError(f"Unexpected endpoint types: {event.endpoints}")

        for endpoint in [ep.strip() for ep in event.endpoints.split(",")]:
            if not endpoint:
                continue

            if endpoint.startswith("file://"):
                socket_endpoints.append(endpoint)
            else:
                tcp_endpoints.append(endpoint)

        db_info: dict[str, Any] = {
            "storageuser": event.username,
            "storagepass": event.password,
            "storageloc": SLURM_ACCT_DB,
        }

        if socket_endpoints:
            # Socket endpoints will be preferred. This is the case when the mysql
            # configuration is using the mysql-router on the local node.
            logger.debug("Updating environment for mysql socket access")
            if len(socket_endpoints) > 1:
                logger.warning(
                    f"{len(socket_endpoints)} socket endpoints are specified, "
                    f"but only first one will be used."
                )
            # Make sure to strip the file:// off the front of the first endpoint
            # otherwise slurmdbd will not be able to connect to the database
            self._slurmdbd.mysql_unix_port = urlparse(socket_endpoints[0]).path
        elif tcp_endpoints:
            # This must be using TCP endpoint and the connection information will
            # be host_address:port. Only one remote mysql service will be configured
            # in this case.
            logger.debug("Using tcp endpoints specified in the relation")
            if len(tcp_endpoints) > 1:
                logger.warning(
                    f"{len(tcp_endpoints)} tcp endpoints are specified, "
                    f"but only the first one will be used."
                )
            addr, port = tcp_endpoints[0].rsplit(":", 1)
            # Check IPv6 and strip any brackets
            if addr.startswith("[") and addr.endswith("]"):
                addr = addr[1:-1]
            db_info.update(
                {
                    "storagehost": addr,
                    "storageport": int(port),
                }
            )
            # Make sure that the MYSQL_UNIX_PORT is removed from the env file.
            del self._slurmdbd.mysql_unix_port
        else:
            # This is 100% an error condition that the charm doesn't know how to handle
            # and is an unexpected condition. This happens when there are commas but no
            # usable data in the endpoints.
            logger.error(f"No endpoints provided: {event.endpoints}")
            self.unit.status = BlockedStatus("No database endpoints provided")
            raise ValueError(f"No endpoints provided: {event.endpoints}")

        self._stored.db_info = db_info
        self._write_config_and_restart_slurmdbd(event)

    def _on_slurmctld_unavailable(self, _: SlurmctldUnavailableEvent) -> None:
        """Reset state and charm status when slurmctld broken."""
        self._check_status()

    @property
    def _ingress_address(self) -> str:
        """Return the ingress_address from the peer relation if it exists."""
        if (peer_binding := self.model.get_binding(PEER_RELATION)) is not None:
            ingress_address = f"{peer_binding.network.ingress_address}"
            logger.debug("slurmdbd ingress_address: %s", ingress_address)
            return ingress_address
        raise IngressAddressUnavailableError("Ingress address unavailable")

    def _assemble_slurmdbd_conf(self) -> SlurmdbdConfig:
        """Assemble and return the SlurmdbdConfig."""
        slurmdbd_config = SlurmdbdConfig.from_dict(
            {
                **CHARM_MAINTAINED_PARAMETERS,
                **self._stored.db_info,
                "dbdhost": self._slurmdbd.hostname,
                "dbdaddr": self._ingress_address,
                **self._stored.user_slurmdbd_params,
            }
        )

        # Check that slurmctld is joined and that we have the
        # jwt_key.
        if self._slurmctld.is_joined and self._slurmdbd.jwt.path.exists():
            slurmdbd_config.auth_alt_types = ["auth/jwt"]
            slurmdbd_config.auth_alt_parameters = {"jwt_key": f"{self._slurmdbd.jwt.path}"}

        logger.debug("slurmdbd.conf: %s", slurmdbd_config.dict() | {"storagepass": "***"})
        return slurmdbd_config

    def _write_config_and_restart_slurmdbd(
        self,
        event: Union[
            ConfigChangedEvent,
            DatabaseCreatedEvent,
            InstallEvent,
            SlurmctldAvailableEvent,
        ],
    ) -> None:
        """Check that we have what we need before we proceed."""
        # Ensure all pre-conditions are met with _check_status(), if not
        # defer the event.
        if not self._check_status():
            event.defer()
            return

        slurmdbd_config = self._assemble_slurmdbd_conf()

        self._slurmdbd.service.stop()
        self._slurmdbd.config.dump(slurmdbd_config)
        self._slurmdbd.service.start()

        # At this point, we must guarantee that slurmdbd is correctly
        # initialized. Its startup might take a while, so we have to wait
        # for it.
        self._check_slurmdbd()

        # Only the leader can set relation data on the application.
        # Enforce that no one other than the leader tries to set
        # application relation data.
        if self.model.unit.is_leader():
            self._slurmctld.set_slurmdbd_host_on_app_relation_data(self._slurmdbd.hostname)

        self._check_status()

    def _check_slurmdbd(self, max_attemps: int = 5) -> None:
        """Ensure slurmdbd is up and running."""
        logger.debug("## Checking if slurmdbd is active")

        for i in range(max_attemps):
            if self._slurmdbd.service.is_active():
                logger.debug("## Slurmdbd running")
                break
            else:
                logger.warning("## Slurmdbd not running, trying to start it")
                self.unit.status = WaitingStatus("starting slurmdbd...")
                self._slurmdbd.service.restart()
                sleep(3 + i)

        if self._slurmdbd.service.is_active():
            self._check_status()
        else:
            self.unit.status = BlockedStatus("cannot start slurmdbd")

    def _check_status(self) -> bool:
        """Check that we have the things we need."""
        if self.unit.is_leader() is False:
            self.unit.status = BlockedStatus(
                "slurmdbd high-availability not supported. see logs for further details"
            )
            return False

        if self._stored.slurm_installed is not True:
            self.unit.status = BlockedStatus(
                "failed to install slurmdbd. see logs for further details"
            )
            return False

        if self._stored.db_info == {}:
            self.unit.status = WaitingStatus("Waiting on: MySQL")
            return False

        if not self._slurmctld.is_joined:
            self.unit.status = BlockedStatus("Need relations: slurmctld")
            return False

        # Account for the case where slurmctld relation has joined
        # but slurmctld hasn't sent the key data yet.
        if self._slurmctld.is_joined and not self._slurmdbd.jwt.path.exists():
            self.unit.status = WaitingStatus("Waiting on: data from slurmctld...")
            return False

        self.unit.status = ActiveStatus()
        return True


if __name__ == "__main__":
    main.main(SlurmdbdCharm)
