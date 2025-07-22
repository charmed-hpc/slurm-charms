#!/usr/bin/env python3
# Copyright 2020-2024 Omnivector, LLC.
# See LICENSE file for licensing details.

"""SlurmrestdCharm."""

import logging

from constants import SLURMRESTD_PORT
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
from slurm_ops import SlurmOpsError, SlurmrestdManager
from slurmutils import SlurmConfig

logger = logging.getLogger()


class SlurmrestdCharm(CharmBase):
    """Operator charm responsible for lifecycle operations for slurmrestd."""

    _stored = StoredState()

    def __init__(self, *args):
        """Initialize charm and configure states and events to observe."""
        super().__init__(*args)

        self._stored.set_default(slurm_installed=False)
        self._stored.set_default(slurmctld_relation_data_available=False)

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
            self._slurmrestd.service.enable()
            self.unit.set_workload_version(self._slurmrestd.version())
            self._stored.slurm_installed = True
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()

        self.unit.open_port("tcp", SLURMRESTD_PORT)
        self._check_status()

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handle update status."""
        self._check_status()

    def _on_slurmctld_available(self, event: SlurmctldAvailableEvent) -> None:
        """Render config and restart the service when we have what we want from slurmctld."""
        if self._stored.slurm_installed is not True:
            event.defer()
            return

        if (event.auth_key is not None) and (event.slurm_conf is not None):
            self._slurmrestd.config.dump(SlurmConfig.from_str(event.slurm_conf))
            self._slurmrestd.key.set(event.auth_key)

            self._stored.slurmctld_relation_data_available = True

            if self._slurmrestd.service.is_active():
                self._slurmrestd.service.restart()
            else:
                self._slurmrestd.service.start()

        self._check_status()

    def _on_slurmctld_unavailable(self, event: SlurmctldUnavailableEvent) -> None:
        """Stop the slurmrestd daemon if slurmctld is unavailable."""
        self._slurmrestd.service.disable()
        self._stored.slurmctld_relation_data_available = False
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

        if self._slurmctld.is_joined and self._stored.slurmctld_relation_data_available is False:
            self.unit.status = WaitingStatus("Waiting on relation data from slurmctld.")
            return False

        if not self._slurmrestd.service.is_active():
            self.unit.status = BlockedStatus("slurmrestd is not starting")
            return False

        self.unit.status = ActiveStatus()
        return True


if __name__ == "__main__":
    main.main(SlurmrestdCharm)
