"""Slurmctld interface for slurmdbd-operator."""

import json
import logging
from typing import List, Union

from ops import (
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
    Relation,
    RelationBrokenEvent,
    RelationChangedEvent,
)

logger = logging.getLogger()


class SlurmctldAvailableEvent(EventBase):
    """Emitted when slurmctld is unavailable."""

    def __init__(self, handle, munge_key, jwt_rsa):
        super().__init__(handle)

        self.munge_key = munge_key
        self.jwt_rsa = jwt_rsa

    def snapshot(self):
        """Snapshot the event data."""
        return {
            "munge_key": self.munge_key,
            "jwt_rsa": self.jwt_rsa,
        }

    def restore(self, snapshot):
        """Restore the snapshot of the event data."""
        self.munge_key = snapshot.get("munge_key")
        self.jwt_rsa = snapshot.get("jwt_rsa")


class SlurmctldUnavailableEvent(EventBase):
    """Emitted when slurmctld joins the relation."""


class Events(ObjectEvents):
    """Slurmctld relation events."""

    slurmctld_available = EventSource(SlurmctldAvailableEvent)
    slurmctld_unavailable = EventSource(SlurmctldUnavailableEvent)


class Slurmctld(Object):
    """Slurmctld interface for slurmdbd."""

    on = Events()  # pyright: ignore [reportIncompatibleMethodOverride, reportAssignmentType]

    def __init__(self, charm, relation_name):
        """Observe relation lifecycle events."""
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

    @property
    def _relations(self) -> Union[List[Relation], None]:
        return self.model.relations.get(self._relation_name)

    @property
    def is_joined(self) -> bool:
        """Return True if self._relation is not None."""
        return True if self._relations else False

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle the relation-changed event.

        Get the cluster_info (munge_key and jwt_rsa) from slurmctld and emit to the charm.
        """
        if app := event.app:
            event_app_data = event.relation.data[app]
            if cluster_info_json := event_app_data.get("cluster_info"):
                try:
                    cluster_info = json.loads(cluster_info_json)
                except json.JSONDecodeError as e:
                    logger.debug(e)
                    raise (e)

                self.on.slurmctld_available.emit(**cluster_info)
                logger.debug(f"## 'cluster_info': {cluster_info}.")
            else:
                logger.debug("'cluster_info' not in application relation data.")
        else:
            logger.debug("## No application in the event.")

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Clear the application relation data and emit the event."""
        self.set_slurmdbd_host_on_app_relation_data("")
        self.on.slurmctld_unavailable.emit()

    def set_slurmdbd_host_on_app_relation_data(self, slurmdbd_host: str) -> None:
        """Send slurmdbd_info to slurmctld."""
        # Iterate over each of the relations setting the relation data.
        if (relations := self._relations) is not None:
            logger.debug(f"## Setting slurmdbd_host on app relation data: {slurmdbd_host}")
            for relation in relations:
                relation.data[self.model.app]["slurmdbd_host"] = slurmdbd_host
        else:
            logger.debug("## No relation, not setting data.")
