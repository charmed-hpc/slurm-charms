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

"""Integration interface implementation for the `slurmdbd` interface."""

__all__ = [
    "AUTH_KEY_LABEL",
    "DatabaseData",
    "SlurmdbdConnectedEvent",
    "SlurmdbdReadyEvent",
    "SlurmdbdDisconnectedEvent",
    "SlurmdbdProvider",
    "SlurmdbdRequirer",
    "SlurmctldReadyEvent",
    "controller_ready",
    "database_ready",
]

from dataclasses import dataclass

import ops
from charmed_hpc_libs.ops.conditions import ConditionEvaluation, leader
from charmed_slurm_slurmctld_interface import (
    AUTH_KEY_LABEL,
    SlurmctldProvider,
    SlurmctldReadyEvent,
    SlurmctldRequirer,
    controller_ready,
)


@dataclass(frozen=True)
class DatabaseData:
    """Data provided by the Slurm database service, `slurmdbd`.

    Attributes:
        hostname: Address of the database service that can be used by the Slurm controller,
        `slurmctld`, for contacting `slurmdbd`.
    """

    hostname: str = ""


def database_ready(charm: ops.CharmBase) -> ConditionEvaluation:
    """Check if database - `slurmdbd` - data is available.

    Notes:
        - This condition check requires that the charm has a public `slurmdbd`
          attribute that has a public `is_ready` method.
    """
    ready = charm.slurmdbd.is_ready()  # type: ignore
    return ConditionEvaluation(ready, "Waiting for database data" if not ready else "")


class SlurmdbdConnectedEvent(ops.RelationEvent):
    """Event emitted when a new `slurmdbd` application is connected to `slurmctld`."""


class SlurmdbdReadyEvent(ops.RelationEvent):
    """Event emitted when the `slurmdbd` application leader is ready.

    Notes:
        - The `slurmdbd` application is "ready" once it is fully initialized and able to share
          all the database information required by the Slurm controller, `slurmctld`.
    """


class SlurmdbdDisconnectedEvent(ops.RelationEvent):
    """Event emitted when a `slurmdbd` application is disconnected from `slurmctld`."""


class _SlurmdbdRequirerEvents(ops.ObjectEvents):
    """`slurmdbd` requirer events."""

    slurmdbd_connected = ops.EventSource(SlurmdbdConnectedEvent)
    slurmdbd_ready = ops.EventSource(SlurmdbdReadyEvent)
    slurmdbd_disconnected = ops.EventSource(SlurmdbdDisconnectedEvent)


class SlurmdbdProvider(SlurmctldRequirer):
    """Integration interface implementation for `slurmdbd` service providers.

    This interface should be used on `slurmdbd` units to retrieve controller data
    from the `slurmctld` application leader.

    Notes:
        - Only the leading `slurmdbd` unit should interact with `slurmctld`.
          All other `slurmdbd` units are peers to be directed by the leader.
    """

    def __init__(self, charm: ops.CharmBase, /, integration_name: str) -> None:
        super().__init__(
            charm, integration_name, required_app_data={"auth_secret_id", "jwt_key_id"}
        )

    @leader
    def _on_relation_created(self, event: ops.RelationCreatedEvent) -> None:
        super()._on_relation_created(event)

    @leader
    def _on_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        super()._on_relation_changed(event)

    @leader
    def _on_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        if self._stored.unit_departing:
            return

        super()._on_relation_broken(event)

    @leader
    def set_database_data(self, data: DatabaseData, /, integration_id: int | None = None) -> None:
        """Set database data in the `slurmdbd` application databag.

        Args:
            data: Database data to set on an integrations' application databag.
            integration_id:
                (Optional) ID of integration to update. If no integration ID is passed,
                all integrations will be updated.

        Warnings:
            - Only the `slurmdbd` application leader can set database configuration data.
        """
        self._save_integration_data(data, self.app, integration_id)


class SlurmdbdRequirer(SlurmctldProvider):
    """Integration interface implementation for `slurmdbd` service requirers.

    This interface should be used on the `slurmctld` application leader to request
    database data from the `slurmdbd` application leader, and provide controller data
    to `slurmdbd` units.
    """

    on = _SlurmdbdRequirerEvents()  # type: ignore

    def __init__(self, charm: ops.CharmBase, /, integration_name: str) -> None:
        super().__init__(charm, integration_name, required_app_data={"hostname"})

        self.framework.observe(
            self.charm.on[self._integration_name].relation_created,
            self._on_relation_created,
        )
        self.framework.observe(
            self.charm.on[self._integration_name].relation_changed,
            self._on_relation_changed,
        )
        self.framework.observe(
            self.charm.on[self._integration_name].relation_broken,
            self._on_relation_broken,
        )

    @leader
    def _on_relation_created(self, event: ops.RelationCreatedEvent) -> None:
        """Handle when a new `slurmdbd` application is connected to `slurmctld`."""
        self.on.slurmdbd_connected.emit(event.relation)

    @leader
    def _on_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Handle when data from the `slurmdbd` application is ready."""
        if not event.relation.data.get(event.relation.app):
            return

        self.on.slurmdbd_ready.emit(event.relation)

    @leader
    def _on_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle when a `slurmdbd` application is disconnected from `slurmctld`."""
        if self._stored.unit_departing:
            return

        super()._on_relation_broken(event)
        self.on.slurmdbd_disconnected.emit(event.relation)

    def get_database_data(self, integration_id: int | None = None) -> DatabaseData:
        """Get database data from the `slurmdbd` application databag.

        Args:
            integration_id: Integration ID to pull database data from.
        """
        return self._load_integration_data(DatabaseData, integration_id=integration_id).pop()
