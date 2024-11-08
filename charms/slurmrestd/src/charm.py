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
from slurmutils.models import SlurmConfig

from charms.hpc_libs.v0.slurm_ops import SlurmOpsError, SlurmrestdManager

logger = logging.getLogger()


class SlurmrestdCharm(CharmBase):
    """Operator charm responsible for lifecycle operations for slurmrestd."""

    _stored = StoredState()

    def __init__(self, *args):
        """Initialize charm and configure states and events to observe."""
        super().__init__(*args)

        self._stored.set_default(slurm_installed=False)

        self._slurmrestd = SlurmrestdManager(snap=False)
        self._slurmctld = Slurmctld(self, "slurmctld")

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
        self.unit.status = WaitingStatus("installing slurmrestd")

        try:
            self._slurmrestd.install()
            self.unit.set_workload_version(self._slurmrestd.version())
            self._stored.slurm_installed = True
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()

        self._check_status()

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handle update status."""
        self._check_status()

    def _on_slurmctld_available(self, event: SlurmctldAvailableEvent) -> None:
        """Render config and restart the service when we have what we want from slurmctld."""
        if self._stored.slurm_installed is not True:
            event.defer()
            return

        if (event.munge_key is not None) and (event.slurm_conf is not None):
            self._slurmrestd.munge.key.set(event.munge_key)
            self._slurmrestd.config.dump(SlurmConfig.from_str(event.slurm_conf))
            self._slurmrestd.munge.service.restart()
            self._slurmrestd.service.restart()

        self._check_status()

    def _on_slurmctld_unavailable(self, event: SlurmctldUnavailableEvent) -> None:
        """Stop the slurmrestd daemon if slurmctld is unavailable."""
        self._slurmrestd.service.disable()
        self._slurmrestd.munge.service.disable()
        self._check_status()

    def _check_status(self) -> bool:
        """Check the status of our integrated applications."""
        if self._stored.slurm_installed is not True:
            self.unit.status = BlockedStatus(
                "failed to install slurmrestd. see logs for further details"
            )
            return False

        if not self._slurmctld.is_joined:
            self.unit.status = BlockedStatus("Need relations: slurmctld")
            return False

        self.unit.status = ActiveStatus()
        return True


if __name__ == "__main__":
    main.main(SlurmrestdCharm)
