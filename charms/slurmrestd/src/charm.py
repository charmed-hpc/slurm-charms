#!/usr/bin/env python3
# Copyright 2020-2024 Omnivector, LLC.
# See LICENSE file for licensing details.

"""SlurmrestdCharm."""

import logging

from interface_slurmctld import Slurmctld, SlurmctldAvailableEvent, SlurmctldUnavailableEvent
from ops import (
    ActiveStatus,
    BlockedStatus,
    CharmBase,
    InstallEvent,
    StoredState,
    UpdateStatusEvent,
    WaitingStatus,
    main,
)
from slurmrestd_ops import LegacySlurmrestdManager, SlurmrestdManager

import charms.hpc_libs.v0.slurm_ops as slurm

logger = logging.getLogger()


class SlurmrestdCharm(CharmBase):
    """Operator charm responsible for lifecycle operations for slurmrestd."""

    _stored = StoredState()

    def __init__(self, *args):
        """Initialize charm and configure states and events to observe."""
        super().__init__(*args)

        self._stored.set_default(slurm_installed=False)

        self._slurmctld = Slurmctld(self, "slurmctld")
        # Legacy manager provides operations we're still fleshing out.
        self._legacy_manager = LegacySlurmrestdManager()
        self._manager = SlurmrestdManager()

        event_handler_bindings = {
            self.on.install: self._on_install,
            self.on.update_status: self._on_update_status,
            self._slurmctld.on.slurmctld_available: self._on_slurmctld_available,
            self._slurmctld.on.slurmctld_unavailable: self._on_slurmctld_unavailable,
        }
        for event, handler in event_handler_bindings.items():
            self.framework.observe(event, handler)

    def _on_install(self, event: InstallEvent) -> None:
        """Perform installation operations for slurmrestd."""
        self.unit.status = WaitingStatus("Installing slurmrestd")

        try:
            self._manager.install()
            self.unit.set_workload_version(slurm.version())
            self._stored.slurm_installed = True
        except slurm.SlurmOpsError as e:
            self.unit.status = BlockedStatus(
                "error installing slurmrestd. check log for more info"
            )
            logger.error(e.message)
            event.defer()
            return

        self._check_status()

    def _on_update_status(self, event: UpdateStatusEvent) -> None:
        """Handle update status."""
        self._check_status()

    def _on_slurmctld_available(self, event: SlurmctldAvailableEvent) -> None:
        """Render config and restart the service when we have what we want from slurmctld."""
        if self._stored.slurm_installed is not True:
            event.defer()
            return

        if (event.munge_key is not None) and (event.slurm_conf is not None):
            self._manager.disable()
            self._manager.munge.disable()
            self._manager.munge.set_key(event.munge_key)
            self._legacy_manager.write_slurm_conf(event.slurm_conf)
            self._manager.munge.enable()
            self._manager.enable()
        self._check_status()

    def _on_slurmctld_unavailable(self, event: SlurmctldUnavailableEvent) -> None:
        """Stop the slurmrestd daemon if slurmctld is unavailable."""
        self._manager.disable()
        self._manager.munge.disable()

        self._check_status()

    def _check_status(self) -> bool:
        """Check the status of our integrated applications."""
        if self._stored.slurm_installed is not True:
            self.unit.status = BlockedStatus("Error installing slurmrestd")
            return False

        if not self._slurmctld.is_joined:
            self.unit.status = BlockedStatus("Need relations: slurmctld")
            return False

        if not self._legacy_manager.check_munged():
            self.unit.status = BlockedStatus("Error configuring munge key")
            return False

        self.unit.status = ActiveStatus()
        return True


if __name__ == "__main__":
    main.main(SlurmrestdCharm)
