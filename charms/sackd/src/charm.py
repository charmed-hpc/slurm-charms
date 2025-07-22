#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Sackd Operator Charm."""

import logging

from constants import SACKD_PORT
from interface_slurmctld import Slurmctld, SlurmctldAvailableEvent
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
from slurm_ops import SackdManager, SlurmOpsError

logger = logging.getLogger(__name__)


class SackdCharm(CharmBase):
    """Sackd lifecycle events."""

    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        """Init _stored attributes and interfaces, observe events."""
        super().__init__(*args, **kwargs)

        self._stored.set_default(
            auth_key=str(),
            sackd_installed=False,
            slurmctld_available=False,
            slurmctld_host=str(),
        )

        self._sackd = SackdManager(snap=False)
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
        """Perform installation operations for sackd."""
        self.unit.status = WaitingStatus("installing sackd")

        try:
            self._sackd.install()
            # Note: sackd is enabled and started by default following
            #       installation via apt.
            #
            # Ensure sackd does not start before relation established.
            self._sackd.service.stop()
            self.unit.set_workload_version(self._sackd.version())
            self._stored.sackd_installed = True
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()

        self.unit.open_port("tcp", SACKD_PORT)
        self._check_status()

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handle update status."""
        self._check_status()

    def _on_slurmctld_available(self, event: SlurmctldAvailableEvent) -> None:
        """Retrieve the slurmctld_available event data and store in charm state."""
        if self._stored.sackd_installed is not True:
            event.defer()
            return

        if (slurmctld_host := event.slurmctld_host) != self._stored.slurmctld_host:
            if slurmctld_host is not None:
                self._sackd.conf_server = [f"{slurmctld_host}:6817"]
                self._stored.slurmctld_host = slurmctld_host
                logger.debug(f"slurmctld_host={slurmctld_host}")
            else:
                logger.debug("'slurmctld_host' not in event data.")
                return

        if (auth_key := event.auth_key) != self._stored.auth_key:
            if auth_key is not None:
                self._stored.auth_key = auth_key
                self._sackd.key.set(auth_key)
            else:
                logger.debug("'auth_key' not in event data.")
                return

        logger.debug("#### Storing slurmctld_available event relation data in charm StoredState.")
        self._stored.slurmctld_available = True

        # Restart sackd after we write event data to respective locations.
        try:
            if self._sackd.service.is_active():
                self._sackd.service.restart()
            else:
                self._sackd.service.start()
        except SlurmOpsError as e:
            logger.error(e)

        self._check_status()

    def _on_slurmctld_unavailable(self, _) -> None:
        """Stop sackd and set slurmctld_available = False when we lose slurmctld."""
        logger.debug("## Slurmctld unavailable")
        self._stored.slurmctld_available = False
        self._stored.auth_key = ""
        self._stored.slurmctld_host = ""
        self._sackd.service.disable()
        self._check_status()

    def _check_status(self) -> None:
        """Check if we have all needed components.

        - sackd installed
        - slurmctld available and working
        - auth key configured and working
        """
        if self._stored.sackd_installed is not True:
            self.unit.status = BlockedStatus(
                "failed to install sackd. see logs for further details"
            )
            return

        if self._slurmctld.is_joined is not True:
            self.unit.status = BlockedStatus("Need relations: slurmctld")
            return

        if self._stored.slurmctld_available is not True:
            self.unit.status = WaitingStatus("Waiting on: slurmctld")
            return

        if not self._sackd.service.is_active():
            self.unit.status = WaitingStatus("Waiting for sackd service to start....")
            return

        self.unit.status = ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    main.main(SackdCharm)
