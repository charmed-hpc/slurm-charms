#!/usr/bin/env python3
# Copyright (c) 2025 Vantage Compute Corporation
# See LICENSE file for licensing details.

"""Slurmdbd Operator Charm."""

# pyright: reportAttributeAccessIssue=false

import logging
from time import sleep
from typing import Any, Dict, Union
from urllib.parse import urlparse

import ops
from constants import CHARM_MAINTAINED_PARAMETERS, SLURM_ACCT_DB, SLURMDBD_PORT
from hpc_libs.slurm_ops import SlurmdbdManager, SlurmOpsError
from interface_slurmctld import Slurmctld, SlurmctldAvailableEvent, SlurmctldUnavailableEvent
from slurmutils.models import SlurmdbdConfig

from charms.data_platform_libs.v0.data_interfaces import DatabaseCreatedEvent, DatabaseRequires
from charms.grafana_agent.v0.cos_agent import COSAgentProvider

logger = logging.getLogger(__name__)


def _convert_db_uri_to_dict(db_uri: str) -> Dict[str, str]:
    """Convert db_uri to  a dict."""
    parsed = urlparse(db_uri)
    db_info = {
        "scheme": parsed.scheme,
        "StorageUser": parsed.username,
        "StoragePass": parsed.password,
        "StorageHost": parsed.hostname,
        "StoragePort": f"{parsed.port}",
        "StorageLoc": parsed.path.lstrip("/"),
    }
    del db_info["scheme"]
    return db_info


class DBURISecretAccessError(RuntimeError):
    """Exception raised when the db-uri secret cannot be accessed."""

    @property
    def message(self) -> str:
        """Return message passed as argument to exception."""
        return self.args[0]


class SlurmdbdCharm(ops.CharmBase):
    """Slurmdbd Charm."""

    _stored = ops.StoredState()

    def __init__(self, *args, **kwargs) -> None:
        """Set the default class attributes."""
        super().__init__(*args, **kwargs)

        self._stored.set_default(
            slurm_installed=False,
            db_info={},
        )

        self._slurmdbd = SlurmdbdManager(snap=False)
        self._slurmctld = Slurmctld(self, "slurmctld")
        self._db = DatabaseRequires(self, relation_name="database", database_name=SLURM_ACCT_DB)
        self._grafana_agent = COSAgentProvider(self)

        event_handler_bindings = {
            self.on.install: self._on_install,
            self.on.update_status: self._on_update_status,
            self.on.config_changed: self._write_config_and_restart_slurmdbd,
            self._db.on.database_created: self._on_database_created,
            self._slurmctld.on.slurmctld_available: self._on_slurmctld_available,
            self._slurmctld.on.slurmctld_unavailable: self._on_slurmctld_unavailable,
            self.on.secret_changed: self._on_secret_changed,
        }
        for event, handler in event_handler_bindings.items():
            self.framework.observe(event, handler)

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Perform installation operations for slurmdbd."""
        self.unit.status = ops.WaitingStatus("installing slurmdbd")
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

    def _on_update_status(self, _: ops.UpdateStatusEvent) -> None:
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
        try:
            db_info = self._get_db_info()
        except DBURISecretAccessError as e:
            self.unit.status = ops.BlockedStatus(e.message)
            logger.error(e.message)
            event.defer()
            return

        if db_info:
            self._write_config_and_restart_slurmdbd(event)

    def _on_secret_changed(self, event: ops.SecretChangedEvent) -> None:
        """Handle secret-changed event."""
        if event.secret.label == "db-uri":
            try:
                db_info = self._get_db_info()
            except DBURISecretAccessError as e:
                self.unit.status = ops.BlockedStatus(e.message)
                logger.error(e.message)
                event.defer()
                return

            if db_info:
                self._write_config_and_restart_slurmdbd(event)

    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Process the DatabaseCreatedEvent and updates the database parameters.

        Updates the database parameters for the slurmdbd configuration based up on the
        DatabaseCreatedEvent. The type of update depends on the endpoints provided in
        the DatabaseCreatedEvent.

        If the endpoints provided are file paths to unix sockets
        then the /etc/default/slurmdbd file will be updated to tell the mySQL client to
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
            self.unit.status = ops.BlockedStatus("No database endpoints provided.")
            raise ValueError(f"Unexpected endpoint types: {event.endpoints}")

        for endpoint in [ep.strip() for ep in event.endpoints.split(",")]:
            if not endpoint:
                continue

            if endpoint.startswith("file://"):
                socket_endpoints.append(endpoint)
            else:
                tcp_endpoints.append(endpoint)

        db_info = {
            "StorageUser": event.username,
            "StoragePass": event.password,
            "StorageLoc": SLURM_ACCT_DB,
        }

        if socket_endpoints:
            # Socket endpoints will be preferred. This is the case when the mysql
            # configuration is using the mysql-router on the local node.
            logger.debug("Updating environment for mysql socket access.")
            if len(socket_endpoints) > 1:
                logger.warning(
                    f"{len(socket_endpoints)} socket endpoints are specified, "
                    f"but only first one will be used."
                )
            # Make sure to strip the file:// off the front of the first endpoint
            # otherwise slurmdbd will not be able to connect to the database.
            self._slurmdbd.mysql_unix_port = urlparse(socket_endpoints[0]).path
        elif tcp_endpoints:
            # This must be using tcp endpoint and the connection information will
            # be host_address:port. Only one remote mysql service will be configured
            # in this case.
            logger.debug("Using TCP endpoints specified in the relation.")
            if len(tcp_endpoints) > 1:
                logger.warning(
                    f"{len(tcp_endpoints)} tcp endpoints are specified, "
                    f"but only the first one will be used."
                )
            addr, port = tcp_endpoints[0].rsplit(":", 1)
            # Check IPv6 and strip any brackets.
            if addr.startswith("[") and addr.endswith("]"):
                addr = addr[1:-1]
            db_info.update(
                {
                    "StorageHost": addr,
                    "StoragePort": port,
                }
            )
            # Make sure that the mysql_unix_port is removed from the env file.
            del self._slurmdbd.mysql_unix_port
        else:
            # This is 100% an error condition that the charm doesn't know how to handle
            # and is an unexpected condition. This happens when there are commas but no
            # usable data in the endpoints.
            logger.error(f"No endpoints provided: {event.endpoints}")
            self.unit.status = ops.BlockedStatus("No database endpoints provided.")
            raise ValueError(f"No endpoints provided: {event.endpoints}")

        self._stored.db_info = db_info
        self._write_config_and_restart_slurmdbd(event)

    def _on_slurmctld_unavailable(self, _: SlurmctldUnavailableEvent) -> None:
        """Reset state and charm status when slurmctld broken."""
        self._check_status()

    def _write_config_and_restart_slurmdbd(
        self,
        event: Union[
            ops.ConfigChangedEvent,
            DatabaseCreatedEvent,
            ops.InstallEvent,
            SlurmctldAvailableEvent,
            ops.SecretChangedEvent,
        ],
    ) -> None:
        """Check that we have what we need before we proceed."""
        if not self._check_status():
            event.defer()
            return

        if (slurmdbd_conf_params := self.config.get("slurmdbd-conf-parameters")) is not None:
            if slurmdbd_conf_params != self._stored.user_supplied_slurmdbd_conf_params:
                logger.debug("## User supplied parameters changed.")
                self._stored.user_supplied_slurmdbd_conf_params = slurmdbd_conf_params

        if binding := self.model.get_binding("slurmctld"):

            try:
                db_info = self._get_db_info()
            except DBURISecretAccessError as e:
                self.unit.status = ops.BlockedStatus(e.message)
                logger.error(e.message)
                event.defer()
                return

            slurmdbd_config = SlurmdbdConfig.from_dict(
                {
                    **CHARM_MAINTAINED_PARAMETERS,
                    **db_info,
                    "DbdHost": self._slurmdbd.hostname,
                    "DbdAddr": f"{binding.network.ingress_address}",
                    **self._get_user_supplied_parameters(),
                }
            )

            # Check that slurmctld is joined and that we have the jwt_key.
            if self._slurmctld.is_joined and self._slurmdbd.jwt.path.exists():
                slurmdbd_config.auth_alt_types = ["auth/jwt"]
                slurmdbd_config.auth_alt_parameters = {"jwt_key": f"{self._slurmdbd.jwt.path}"}

            self._slurmdbd.service.stop()
            self._slurmdbd.config.dump(slurmdbd_config)
            self._slurmdbd.service.start()

            # At this point, we must guarantee that slurmdbd is correctly
            # initialized. Its startup might take a while, so we have to wait for it.
            self._check_slurmdbd()

            # Only the leader can set relation data on the application.
            # Enforce that no one other than the leader tries to set application relation data.
            if self.model.unit.is_leader():
                self._slurmctld.set_slurmdbd_host_on_app_relation_data(self._slurmdbd.hostname)
        else:
            msg = "Cannot get network binding, please debug."
            self.unit.status = ops.BlockedStatus(msg)
            logger.error(msg)

        self._check_status()

    def _get_db_info(self) -> Dict[Any, Any]:
        """Determine if user supplied db configuration."""
        db_uri = ""

        def _handle_secret_error(error: Exception, secret_id: str, reason: str) -> None:
            """Consolidated secret error handler."""
            msg = f"Cannot access secret: {secret_id}. {reason}"
            self.unit.status = ops.BlockedStatus(msg)
            logger.error(f"{msg} - {getattr(error, 'message', str(error))}")
            raise DBURISecretAccessError(msg)

        if (db_uri_secret_id := self.config.get("db-uri-secret-id")) is not None:

            logger.debug(f"Attempting to retrieve secret: {db_uri_secret_id}")
            try:
                db_uri_secret = self.model.get_secret(id=f"{db_uri_secret_id}")
                db_uri = db_uri_secret.get_content(refresh=True)["db-uri"]
            except ops.SecretNotFoundError as e:
                self._handle_secret_error(e, f"{db_uri_secret_id}", "Does not exist.")
            except ops.ModelError as e:
                self._handle_secret_error(e, f"{db_uri_secret_id}", "Insufficient privileges.")
            except KeyError as e:
                self._handle_secret_error(
                    e, f"{db_uri_secret_id}", "Cannot access secret content 'db-uri'."
                )
        else:
            logger.debug("No user supplied db-uri.")
            return self._stored.db_info

        return _convert_db_uri_to_dict(db_uri)

    def _get_user_supplied_parameters(self) -> Dict[Any, Any]:
        """Gather, parse, and return the user supplied parameters."""
        user_supplied_parameters = {}
        if custom_config := self.config.get("slurmdbd-conf-parameters"):
            try:
                user_supplied_parameters = {
                    line.split("=")[0]: line.split("=")[1]
                    for line in str(custom_config).split("\n")
                    if not line.startswith("#") and line.strip() != ""
                }
            except IndexError as e:
                logger.error(f"Could not parse user supplied parameters: {e}.")
        return user_supplied_parameters

    def _check_slurmdbd(self, max_attemps: int = 5) -> None:
        """Ensure slurmdbd is up and running."""
        logger.debug("## checking if slurmdbd is active")

        for i in range(max_attemps):
            if self._slurmdbd.service.active():
                logger.debug("## slurmdbd running")
                break
            else:
                logger.warning("## slurmdbd not running, trying to start it")
                self.unit.status = ops.WaitingStatus("starting slurmdbd...")
                self._slurmdbd.service.restart()
                sleep(3 + i)

        if self._slurmdbd.service.active():
            self._check_status()
        else:
            self.unit.status = ops.BlockedStatus("Cannot start slurmdbd.")

    def _check_status(self) -> bool:
        """Check that we have the things we need."""
        if self.unit.is_leader() is False:
            self.unit.status = ops.BlockedStatus(
                "slurmdbd high-availability not supported. see logs for further details"
            )
            return False

        if self._stored.slurm_installed is not True:
            self.unit.status = ops.BlockedStatus(
                "Failed to install slurmdbd, see logs for further details."
            )
            return False

        try:
            db_info = self._get_db_info()
        except DBURISecretAccessError as e:
            self.unit.status = ops.BlockedStatus(e.message)
            logger.error(e.message)
            return False

        if db_info == {}:
            self.unit.status = ops.WaitingStatus("Waiting on: MySQL")
            return False

        # Account for the case where slurmctld relation has joined
        # but slurmctld hasn't sent the key data yet.
        if self._slurmctld.is_joined and not self._slurmdbd.jwt.path.exists():
            self.unit.status = ops.WaitingStatus("Waiting on: data from slurmctld...")
            return False

        self.unit.status = ops.ActiveStatus()
        return True


if __name__ == "__main__":
    ops.main(SlurmdbdCharm)
