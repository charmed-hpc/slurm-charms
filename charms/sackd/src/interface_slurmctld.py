"""Slurmctld interface for sackd."""

import json
import logging

from ops import (
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
    RelationBrokenEvent,
    RelationChangedEvent,
)

logger = logging.getLogger(__name__)


class SlurmctldAvailableEvent(EventBase):
    """Emitted when slurmctld is available."""

    def __init__(
        self,
        handle,
        auth_key,
        slurmctld_hosts,
    ):
        super().__init__(handle)

        self.auth_key = auth_key
        self.slurmctld_hosts = slurmctld_hosts

    def snapshot(self):
        """Snapshot the event data."""
        return {
            "auth_key": self.auth_key,
            "slurmctld_hosts": self.slurmctld_hosts,
        }

    def restore(self, snapshot):
        """Restore the snapshot of the event data."""
        self.auth_key = snapshot.get("auth_key")
        self.slurmctld_hosts = snapshot.get("slurmctld_hosts")


class SlurmctldUnavailableEvent(EventBase):
    """Emit when the relation to slurmctld is broken."""


class Events(ObjectEvents):
    """Sackd emitted events."""

    slurmctld_available = EventSource(SlurmctldAvailableEvent)
    slurmctld_unavailable = EventSource(SlurmctldUnavailableEvent)


class Slurmctld(Object):
    """Slurmctld integration."""

    on = Events()  # pyright: ignore [reportIncompatibleMethodOverride, reportAssignmentType]

    def __init__(self, charm, relation_name):
        """Set initial data and observe interface events."""
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

        self.framework.observe(
            self._charm.on[self._relation_name].relation_changed,
            self._on_relation_changed,
        )

        self.framework.observe(
            self._charm.on[self._relation_name].relation_broken,
            self._on_relation_broken,
        )

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle the relation-changed event.

        Get the cluster_info from slurmctld and emit the slurmctld_available event.

        Ensure all cases are accounted for:
            - no application in event
            - no application data in relation
            - no cluster_info in application relation data
            - application exists in event, and application data exists on relation, cluster_info
              exists in application relation data
        """
        if app := event.app:
            if app_data := event.relation.data.get(app):
                if cluster_info_json := app_data.get("cluster_info"):
                    try:
                        cluster_info = json.loads(cluster_info_json)
                    except json.JSONDecodeError as e:
                        logger.error(e)
                        raise (e)

                    logger.debug(f"cluster_info: {cluster_info}")
                    self.on.slurmctld_available.emit(**cluster_info)
                else:
                    logger.debug(
                        f"No cluster_info in application data, deferring {self._relation_name}"
                    )
                    event.defer()
            else:
                logger.debug("No application data on relation.")
        else:
            logger.debug("No application on the event.")

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Emit slurmctld_unavailable when the relation-broken event occurs."""
        self.on.slurmctld_unavailable.emit()

    @property
    def is_joined(self) -> bool:
        """Return True if relation(s) are joined."""
        return all(self.model.relations.get(self._relation_name, ()))
