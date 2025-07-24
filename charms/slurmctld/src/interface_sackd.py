"""Slurmctld interface to sackd."""

import json
import logging

from ops import Object, RelationBrokenEvent, RelationCreatedEvent

logger = logging.getLogger()


class Sackd(Object):
    """Sackd inventory interface."""

    def __init__(self, charm, relation_name):
        """Set self._relation_name and self.charm."""
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

        self.framework.observe(
            self._charm.on[self._relation_name].relation_created,
            self._on_relation_created,
        )

        self.framework.observe(
            self._charm.on[self._relation_name].relation_broken,
            self._on_relation_broken,
        )

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Set our data on the relation."""
        if not self.framework.model.unit.is_leader():
            return

        auth_key = self._charm.get_auth_key()
        if not auth_key:
            logger.debug("auth key not yet available. deferring event")
            event.defer()
            return

        if not self._charm.all_units_observed():
            logger.debug("not observed all other controller units. deferring event")
            event.defer()
            return

        event.relation.data[self.model.app]["cluster_info"] = json.dumps(
            {
                "auth_key": auth_key,
                "slurmctld_hosts": self._charm.get_controllers(),
            }
        )

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Clear the cluster info if the relation is broken."""
        # Avoid cluster info being cleared in instance where leader unit is removed but other units
        # remain by proceeding only if all units are departing/application is being scaled to 0.
        if self.framework.model.unit.is_leader() and self.model.app.planned_units() == 0:
            event.relation.data[self.model.app]["cluster_info"] = ""

    def update_controllers(self) -> None:
        """Synchronize the current set of slurmctld controllers with data on the relation."""
        for rel in self.model.relations.get(self._relation_name, ()):
            if rel and "cluster_info" in rel.data[self.model.app]:
                cluster_info = json.loads(rel.data[self.model.app]["cluster_info"])
                cluster_info["slurmctld_hosts"] = self._charm.get_controllers()
                rel.data[self.model.app]["cluster_info"] = json.dumps(cluster_info)
                logger.debug("sackd cluster_info set to %s", cluster_info)
