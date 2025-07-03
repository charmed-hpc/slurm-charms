# Copyright (c) 2025 Omnivector, LLC
# See LICENSE file for licensing details.

"""SlurmctldPeer."""

import logging
import secrets
import time
from typing import Optional

from constants import CLUSTER_NAME_PREFIX
from ops import (
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
    RelationChangedEvent,
    RelationCreatedEvent,
    RelationDepartedEvent,
)

logger = logging.getLogger()


class SlurmctldPeerError(Exception):
    """Exception raised from slurmctld-peer interface errors."""

    @property
    def message(self) -> str:
        """Return message passed as argument to exception."""
        return self.args[0]


class SlurmctldAvailableEvent(EventBase):
    """Emitted when a new controller instance joins."""


class SlurmctldDepartedEvent(EventBase):
    """Emitted when a controller leaves."""


class Events(ObjectEvents):
    """Interface events."""

    slurmctld_available = EventSource(SlurmctldAvailableEvent)
    slurmctld_departed = EventSource(SlurmctldDepartedEvent)


class SlurmctldPeer(Object):
    """SlurmctldPeer Interface."""

    on = Events()  # pyright: ignore [reportIncompatibleMethodOverride, reportAssignmentType]

    def __init__(self, charm, relation_name):
        """Initialize the interface."""
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

        self.framework.observe(
            self._charm.on[self._relation_name].relation_created,
            self._on_relation_created,
        )
        self.framework.observe(
            self._charm.on[self._relation_name].relation_changed,
            self._on_relation_changed,
        )
        self.framework.observe(
            self._charm.on[self._relation_name].relation_departed,
            self._on_relation_departed,
        )

    @property
    def _relation(self):
        """Slurmctld peer relation."""
        if relation := self.framework.model.get_relation(self._relation_name):
            return relation
        raise SlurmctldPeerError("attempted to access peer relation before it was established")

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        self._relation.data[self._charm.unit]["hostname"] = self._charm.hostname
        if not self._charm.unit.is_leader():
            return

        if self.cluster_name is None:
            if (charm_config_cluster_name := self._charm.config.get("cluster-name", "")) != "":
                cluster_name = charm_config_cluster_name
            else:
                cluster_name = f"{CLUSTER_NAME_PREFIX}-{secrets.token_urlsafe(3)}"

            logger.debug(f"Cluster Name: {cluster_name}")
            self.cluster_name = cluster_name

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        # Workaround for `scontrol reconfigure` not signalling slurmctld to reload slurm.conf.
        # Use the peer relation to trigger a restart ourselves.
        # Note: must be a restart. Reloading causes the slurmctld process to exit.
        restart_signal = self._relation.data[self.model.app].get("restart_signal", "")
        if restart_signal != self._charm._stored.last_restart_signal:
            logger.debug("restart signal found. restarting slurmctld")
            self._charm._stored.last_restart_signal = restart_signal

            # Leader already restarted its service when writing out slurm.conf
            if not self._charm.unit.is_leader():
                self._charm._slurmctld.service.restart()

            return

        # Fire only once the leader unit has completed relation-joined for all units
        if self._charm.unit.is_leader() and self.all_units_observed():
            self.on.slurmctld_available.emit()
            return

    def _on_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Handle hook when a unit departs."""
        # Fire only once the leader unit has seen the last departing unit leave
        if self._charm.unit.is_leader() and self.all_units_observed():

            if event.departing_unit == self._charm.unit:
                logger.debug(
                    "leader is departing. next elected leader must refresh controller config"
                )
                self._charm._slurmctld.service.stop()
                return

            self.on.slurmctld_departed.emit()

    def all_units_observed(self) -> bool:
        """Return True if this unit has observed all other units in the peer relation. False otherwise."""
        try:
            seen_units = len(self._relation.units)
        except SlurmctldPeerError:
            seen_units = 0

        planned_units = self.model.app.planned_units() - 1  # -1 as includes self
        logger.debug("seen %s other slurmctld unit(s) of planned %s", seen_units, planned_units)
        return seen_units == planned_units

    def signal_slurmctld_restart(self) -> None:
        """Add a message to the peer relation to indicate all peers should restart slurmctld.service.

        This is a workaround for `scontrol reconfigure` not instructing all slurmctld daemons to
        re-read SlurmctldHost lines from slurm.conf.
        """
        if not self._charm.unit.is_leader():
            logger.warning("non-leader attempted to signal a slurmctld restart across peers")
            return

        # Current timestamp used so a unique value is written to the relation on each call.
        signal = str(time.time())
        self._relation.data[self.model.app]["restart_signal"] = signal

    @property
    def controllers(self) -> list:
        """Return the list of controllers."""
        try:
            logger.debug(
                "gathering controller hostnames from peer relation: %s", self._relation.data
            )
            return [
                data["hostname"] for data in self._relation.data.values() if "hostname" in data
            ]
        except SlurmctldPeerError:
            return []

    @property
    def cluster_name(self) -> Optional[str]:
        """Return the cluster_name from app relation data."""
        cluster_name = None
        try:
            if cluster_name_from_relation := self._relation.data[self.model.app].get(
                "cluster_name"
            ):
                cluster_name = cluster_name_from_relation
            logger.debug(f"## `slurmctld-peer` relation available. cluster_name: {cluster_name}.")
        except SlurmctldPeerError:
            logger.debug(
                "## `slurmctld-peer` relation not available yet, cannot get cluster_name."
            )
        return cluster_name

    @cluster_name.setter
    def cluster_name(self, name: str) -> None:
        """Set the cluster_name on app relation data."""
        if not self.framework.model.unit.is_leader():
            logger.debug("only leader can set the Slurm cluster name")
            return

        try:
            self._relation.data[self.model.app]["cluster_name"] = name
        except SlurmctldPeerError as e:
            e.add_note("cannot set cluster_name")
            raise
