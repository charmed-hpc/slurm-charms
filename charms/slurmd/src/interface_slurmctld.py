"""Slurmctld interface for slurmd."""

import json
import logging
from typing import Union

from ops import (
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
    Relation,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationCreatedEvent,
)

logger = logging.getLogger(__name__)


class SlurmctldAvailableEvent(EventBase):
    """Emitted when slurmctld is available."""

    def __init__(
        self,
        handle,
        cluster_name,
        munge_key,
        nhc_params,
        slurmctld_host,
    ):
        super().__init__(handle)

        self.cluster_name = cluster_name
        self.munge_key = munge_key
        self.nhc_params = nhc_params
        self.slurmctld_host = slurmctld_host

    def snapshot(self):
        """Snapshot the event data."""
        return {
            "cluster_name": self.cluster_name,
            "munge_key": self.munge_key,
            "nhc_params": self.nhc_params,
            "slurmctld_host": self.slurmctld_host,
        }

    def restore(self, snapshot):
        """Restore the snapshot of the event data."""
        self.cluster_name = snapshot.get("cluster_name")
        self.munge_key = snapshot.get("munge_key")
        self.nhc_params = snapshot.get("nhc_params")
        self.slurmctld_host = snapshot.get("slurmctld_host")


class SlurmctldUnavailableEvent(EventBase):
    """Emit when the relation to slurmctld is broken."""


class Events(ObjectEvents):
    """Slurmd emitted events."""

    slurmctld_available = EventSource(SlurmctldAvailableEvent)
    slurmctld_unavailable = EventSource(SlurmctldUnavailableEvent)


class Slurmctld(Object):
    """Slurmctld integration for slurmd."""

    on = Events()  # pyright: ignore [reportIncompatibleMethodOverride, reportAssignmentType]

    def __init__(self, charm, relation_name):
        """Set initial data and observe interface events."""
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
        """Handle the relation-created event.

        Set the node and partition config on the relation.
        """
        self.set_node()

        if self.model.unit.is_leader():
            self.set_partition()

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

    def set_node(self) -> None:
        """Set the node on the unit data."""
        if relation := self._relation:
            relation.data[self.model.unit]["node"] = json.dumps(self._charm.get_node())
        else:
            logger.debug("No relation, cannot set 'node'.")

    def set_partition(self) -> None:
        """Set the slurmd partition on the app relation data.

        Setting data on the application relation forces the units of related
        slurmctld application(s) to observe the relation-changed
        event so they can acquire and redistribute the updated slurm config.
        """
        if relation := self._relation:
            relation.data[self.model.app]["partition"] = json.dumps(self._charm.get_partition())
        else:
            logger.debug("No relation, cannot set 'partition'.")

    @property
    def _relation(self) -> Union[Relation, None]:
        """Return the relation."""
        return self.model.get_relation(self._relation_name)

    @property
    def is_joined(self) -> bool:
        """Return True if relation is joined."""
        return True if self.model.relations.get(self._relation_name) else False
