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
        # Need to wait until the charm has installed slurm before we can proceed.
        if not self._charm.slurm_installed:
            event.defer()
            return

        event.relation.data[self.model.app]["cluster_info"] = json.dumps(
            {
                "auth_key": self._charm.get_munge_key(),  # TODO: change this once munge is auth/slurm
                "slurmctld_host": self._charm.hostname,
            }
        )

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Clear the cluster info if the relation is broken."""
        if self.framework.model.unit.is_leader():
            event.relation.data[self.model.app]["cluster_info"] = ""
