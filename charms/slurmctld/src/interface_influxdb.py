# Copyright 2025 Omnivector, LLC
# See LICENSE file for licensing details.

"""Influxdb interface."""

import json
import logging
import secrets
from typing import TYPE_CHECKING

import influxdb
import requests
from influxdb.exceptions import InfluxDBClientError
from ops import (
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
    RelationBrokenEvent,
    RelationJoinedEvent,
)

if TYPE_CHECKING:
    from charm import SlurmctldCharm

logger = logging.getLogger()


class InfluxDBAvailableEvent(EventBase):
    """InfluxDBAvailable event."""

    def __init__(
        self,
        handle,
        influxdb_host,
        influxdb_user,
        influxdb_pass,
        influxdb_database,
        influxdb_policy,
    ):
        super().__init__(handle)

        self.influxdb_host = influxdb_host
        self.influxdb_user = influxdb_user
        self.influxdb_pass = influxdb_pass
        self.influxdb_database = influxdb_database
        self.influxdb_policy = influxdb_policy

    def snapshot(self):
        """Snapshot the event data."""
        return {
            "influxdb_host": self.influxdb_host,
            "influxdb_user": self.influxdb_user,
            "influxdb_pass": self.influxdb_pass,
            "influxdb_database": self.influxdb_database,
            "influxdb_policy": self.influxdb_policy,
        }

    def restore(self, snapshot):
        """Restore the snapshot of the event data."""
        self.influxdb_host = snapshot.get("influxdb_host")
        self.influxdb_user = snapshot.get("influxdb_user")
        self.influxdb_pass = snapshot.get("influxdb_pass")
        self.influxdb_database = snapshot.get("influxdb_database")
        self.influxdb_policy = snapshot.get("influxdb_policy")


class InfluxDBUnavailableEvent(EventBase):
    """InfluxDBUnavailable event."""


class InfluxDBEvents(ObjectEvents):
    """InfluxDBEvents."""

    influxdb_available = EventSource(InfluxDBAvailableEvent)
    influxdb_unavailable = EventSource(InfluxDBUnavailableEvent)


class InfluxDB(Object):
    """InfluxDB interface."""

    _on = InfluxDBEvents()

    def __init__(self, charm: "SlurmctldCharm", relation_name: str) -> None:
        """Observe relation events."""
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

        self._INFLUX_USER = "slurm"
        self._INFLUX_PRIVILEGE = "all"
        self._INFLUX_POLICY_NAME = "charmed-hpc"

        self.framework.observe(
            self._charm.on[self._relation_name].relation_joined,
            self._on_relation_joined,
        )

        self.framework.observe(
            self._charm.on[self._relation_name].relation_broken,
            self._on_relation_broken,
        )

    def _on_relation_joined(self, event: RelationJoinedEvent) -> None:
        """Store influxdb_ingress in the charm."""
        if self.framework.model.unit.is_leader():
            logger.debug("Slurmctld Leader influxdb._on_relation_joined()")

            if (app_data := event.relation.data.get(self.model.app)) is not None:
                logger.debug(f"Influxdb interface app data: {app_data}")

                influxdb_admin_info = app_data.get("influxdb_admin_info", "")

                if influxdb_admin_info != "":
                    return

                if unit := event.unit:
                    logger.debug(f"Influxdb unit: {unit}")
                    if (unit_data := event.relation.data.get(unit)) is not None:
                        admin_info = {"host": "", "port": "", "user": "", "password": ""}
                        if host := unit_data.get("ingress-address"):
                            admin_info["host"] = host
                        if port := unit_data.get("port"):
                            admin_info["port"] = port
                        if username := unit_data.get("user"):
                            admin_info["user"] = username
                        if password := unit_data.get("password"):
                            admin_info["password"] = password

                        if all(admin_info.values()):
                            app_data["influxdb_admin_info"] = json.dumps(admin_info)

                            # Influxdb client
                            client = influxdb.InfluxDBClient(
                                host=admin_info["host"],
                                port=int(admin_info["port"]),
                                username=admin_info["user"],
                                password=admin_info["password"],
                            )

                            # Influxdb slurm user password
                            influx_slurm_password = secrets.token_urlsafe(32)

                            # Only create the user and db if they don't already exist
                            users = [db["user"] for db in client.get_list_users()]
                            logger.debug(f"## users in influxdb: {users}")
                            if self._INFLUX_USER not in users:
                                logger.debug(f"## Creating influxdb user: {self._INFLUX_USER}")
                                client.create_user(self._INFLUX_USER, influx_slurm_password)

                            databases = [db["name"] for db in client.get_list_database()]
                            database_name = self._charm.slurmctld_peer.cluster_name

                            if self._charm.slurmctld_peer.cluster_name not in databases:
                                logger.debug(
                                    f"## Creating influxdb db: {self._charm.slurmctld_peer.cluster_name}"
                                )
                                client.create_database(database_name)

                            client.grant_privilege(
                                self._INFLUX_PRIVILEGE, database_name, self._INFLUX_USER
                            )

                            policies = [
                                policy["name"]
                                for policy in client.get_list_retention_policies(database_name)
                            ]
                            if self._INFLUX_POLICY_NAME not in policies:
                                # Create the default retention policy
                                logger.debug(
                                    f"## Creating influxdb retention policy: {self._INFLUX_POLICY_NAME}"
                                )
                                client.create_retention_policy(
                                    name=self._INFLUX_POLICY_NAME,
                                    duration="7d",
                                    replication="1",
                                    database=database_name,
                                    default=True,
                                )

                            # Emit influxdb connection info
                            self._on.influxdb_available.emit(
                                f"{admin_info['host']}:{admin_info['port']}",
                                self._INFLUX_USER,
                                influx_slurm_password,
                                database_name,
                                self._INFLUX_POLICY_NAME,
                            )

                        else:
                            logger.debug("Influxdb admin connection info incomplete.")
                            event.defer()
                    else:
                        logger.debug("No unit_data available in the event.")
                        event.defer()
                else:
                    logger.debug("No units in the event.")
                    event.defer()
            else:
                logger.debug("Application not available on the relation.")
                event.defer()
        else:
            logger.debug("Slurmctld unit not leader - skipping hook event.")

        return

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Remove the database and user from influxdb on relation-broken."""
        if self.framework.model.unit.is_leader():
            if (app_data := event.relation.data.get(self.model.app)) is not None:
                logger.debug(f"Infulxdb interface app data: {app_data}")

                influxdb_admin_info = app_data.get("influxdb_admin_info", "")

                if influxdb_admin_info != "":
                    admin_info = json.loads(influxdb_admin_info)
                    try:
                        client = influxdb.InfluxDBClient(
                            host=admin_info["host"],
                            port=int(admin_info["port"]),
                            username=admin_info["user"],
                            password=admin_info["password"],
                        )

                        databases = [db["name"] for db in client.get_list_database()]
                        database_name = self._charm.slurmctld_peer.cluster_name

                        if database_name in databases:
                            client.drop_database(database_name)

                        users = [db["user"] for db in client.get_list_users()]
                        if self._INFLUX_USER in users:
                            client.drop_user(self._INFLUX_USER)

                        policies = [
                            policy["name"]
                            for policy in client.get_list_retention_policies(database_name)
                        ]
                        if self._INFLUX_POLICY_NAME in policies:
                            client.drop_retention_policy(
                                self._INFLUX_POLICY_NAME, database=database_name
                            )
                    except InfluxDBClientError as e:
                        logger.debug(e)
                    except requests.exceptions.ConnectionError as e:
                        logger.debug(e)

                    app_data["influxdb_admin_info"] = ""
                    self._on.influxdb_unavailable.emit()

                else:
                    logger.debug("No influxdb admin info available.")
            else:
                logger.debug("No app_data available.")
        else:
            logger.debug("Slurmctld unit not leader - skipping hook event.")
