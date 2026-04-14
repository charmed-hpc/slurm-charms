# Copyright 2025-2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Integration interface implementation for the `sackd` interface."""

__all__ = [
    "AUTH_KEY_LABEL",
    "SackdConnectedEvent",
    "SackdProvider",
    "SackdRequirer",
    "SlurmctldDisconnectedEvent",
    "SlurmctldReadyEvent",
    "controller_ready",
]


import ops
from charmed_hpc_libs.ops import leader
from charmed_slurm_slurmctld_interface import (
    AUTH_KEY_LABEL,
    SlurmctldDisconnectedEvent,
    SlurmctldProvider,
    SlurmctldReadyEvent,
    SlurmctldRequirer,
    controller_ready,
)

_REQUIRED_APP_DATA = {
    "auth_secret_id": lambda value: value != '""',
    "controllers": lambda value: value != "[]",
}


def _sackd_app_data_validator(data: ops.RelationDataContent) -> bool:
    """Validate data sent by `slurmctld` stored in the `sackd` integration."""
    return all(validate(data[k]) for k, validate in _REQUIRED_APP_DATA.items())


class SackdConnectedEvent(ops.RelationEvent):
    """Event emitted when a new `sackd` application is connected to `slurmctld`."""


class _SackdRequirerEvents(ops.ObjectEvents):
    """`sackd` requirer events."""

    sackd_connected = ops.EventSource(SackdConnectedEvent)


class SackdProvider(SlurmctldRequirer):
    """Integration interface implementation for `sackd` service providers.

    This interface should be used on `sackd` units to retrieve controller data
    from the `slurmctld` application leader.
    """

    def __init__(self, charm: ops.CharmBase, /, integration_name: str) -> None:
        super().__init__(
            charm,
            integration_name,
            required_app_data=set(_REQUIRED_APP_DATA),
            app_data_validator=_sackd_app_data_validator,
        )


class SackdRequirer(SlurmctldProvider):
    """Integration interface implementation for `sackd` service requirers.

    This interface should be used on the `slurmctld` application leader to provide
    Slurm controller data to `sackd` units.
    """

    on = _SackdRequirerEvents()  # type: ignore

    def __init__(self, charm: ops.CharmBase, /, integration_name: str) -> None:
        super().__init__(charm, integration_name)

        self.framework.observe(
            self.charm.on[self._integration_name].relation_created,
            self._on_relation_created,
        )

    @leader
    def _on_relation_created(self, event: ops.RelationCreatedEvent) -> None:
        """Handle when a new `sackd` application is connected to `slurmctld`."""
        self.on.sackd_connected.emit(event.relation)
