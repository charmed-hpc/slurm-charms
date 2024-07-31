"""Slurmctld interface to slurmdbd."""

import json
import logging

from ops import (
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationCreatedEvent,
)

logger = logging.getLogger()


class SlurmdbdAvailableEvent(EventBase):
    """Emitted when slurmctld is available."""

    def __init__(self, handle, slurmdbd_host):
        super().__init__(handle)

        self.slurmdbd_host = slurmdbd_host

    def snapshot(self):
        """Snapshot the event data."""
        return {"slurmdbd_host": self.slurmdbd_host}

    def restore(self, snapshot):
        """Restore the snapshot of the event data."""
        self.slurmdbd_host = snapshot.get("slurmdbd_host")


class SlurmdbdUnavailableEvent(EventBase):
    """Emits slurmdbd_unavailable."""


class Events(ObjectEvents):
    """Slurmdbd interface events."""

    slurmdbd_available = EventSource(SlurmdbdAvailableEvent)
    slurmdbd_unavailable = EventSource(SlurmdbdUnavailableEvent)


class Slurmdbd(Object):
    """Facilitate slurmdbd lifecycle events."""

    on = Events()  # pyright: ignore [reportIncompatibleMethodOverride, reportAssignmentType]

    def __init__(self, charm, relation_name):
        """Set the initial attribute values for this interface."""
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
            self._charm.on[self._relation_name].relation_broken,
            self._on_relation_broken,
        )

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Perform relation-created event operations."""
        # Check that slurm has been installed so that we know the munge key is
        # available. Defer if slurm has not been installed yet.
        if not self._charm.slurm_installed:
            event.defer()
            return

        try:
            event.relation.data[self.model.app]["cluster_info"] = json.dumps(
                {
                    "munge_key": self._charm.get_munge_key(),
                    "jwt_rsa": self._charm.get_jwt_rsa(),
                }
            )
        except json.JSONDecodeError as e:
            logger.error(e)
            raise (e)

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Retrieve the slurmdbd_host from the relation and emit slurmdbd_available."""
        if event.app and event.unit:
            if event_app_data := event.relation.data.get(event.app):
                if slurmdbd_host := event_app_data.get("slurmdbd_host"):
                    self.on.slurmdbd_available.emit(slurmdbd_host)
                else:
                    logger.debug("'slurmdbd_host' data does not exist on relation.")
                    event.defer()
            else:
                logger.debug("Application does not exist on relation.")
                event.defer()

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Clear the relation data on the application."""
        if self.framework.model.unit.is_leader():
            event.relation.data[self.model.app]["cluster_info"] = ""
        self.on.slurmdbd_unavailable.emit()
