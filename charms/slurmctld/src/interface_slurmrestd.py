"""Slurmctld interface to slurmrestd."""

import logging

from ops import (
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
    RelationBrokenEvent,
    RelationCreatedEvent,
)

logger = logging.getLogger()


class SlurmrestdAvailableEvent(EventBase):
    """Emitted when slurmrestd is available."""


class SlurmrestdUnavailableEvent(EventBase):
    """Emitted when the slurmrestd relation is broken."""


class Events(ObjectEvents):
    """Slurmrestd interface events."""

    slurmrestd_available = EventSource(SlurmrestdAvailableEvent)
    slurmrestd_unavailable = EventSource(SlurmrestdUnavailableEvent)


class Slurmrestd(Object):
    """Slurmrestd interface."""

    on = Events()  # pyright: ignore [reportIncompatibleMethodOverride, reportAssignmentType]

    def __init__(self, charm, relation_name):
        """Set the initial data."""
        super().__init__(charm, relation_name)

        self._charm = charm
        self._relation_name = relation_name

        self.framework.observe(
            self._charm.on[relation_name].relation_created, self._on_relation_created
        )
        self.framework.observe(
            self._charm.on[relation_name].relation_broken, self._on_relation_broken
        )

    @property
    def is_joined(self) -> bool:
        """Return True if relation is joined."""
        return True if self.model.relations.get(self._relation_name) else False

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        # Check that slurm has been installed so that we know the munge key is
        # available. Defer if slurm has not been installed yet.
        if not self._charm.slurm_installed:
            event.defer()
            return

        # Get the munge_key from the slurm_ops_manager and set it to the app
        # data on the relation to be retrieved on the other side by slurmdbd.
        app_relation_data = event.relation.data[self.model.app]
        app_relation_data["munge_key"] = self._charm.get_munge_key()
        self.on.slurmrestd_available.emit()

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        self.on.slurmrestd_unavailable.emit()

    def set_slurm_config_on_app_relation_data(self, slurm_config: str) -> None:
        """Set the slurm_conifg to the app data on the relation.

        Setting data on the relation forces the units of related applications
        to observe the relation-changed event so they can acquire and
        render the updated slurm_config.
        """
        relations = self._charm.framework.model.relations.get(self._relation_name)
        for relation in relations:
            app_relation_data = relation.data[self.model.app]
            app_relation_data["slurm_conf"] = slurm_config
