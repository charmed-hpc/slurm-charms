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
"""Integration interface implementation for the `slurmd` interface."""

__all__ = [
    "AUTH_KEY_LABEL",
    "ComputeData",
    "SlurmdConnectedEvent",
    "SlurmdReadyEvent",
    "SlurmdDisconnectedEvent",
    "SlurmdProvider",
    "SlurmdRequirer",
    "SlurmctldConnectedEvent",
    "SlurmctldDisconnectedEvent",
    "SlurmctldReadyEvent",
    "controller_ready",
    "partition_ready",
]

from dataclasses import dataclass

import ops
from charmed_hpc_libs.ops import ConditionEvaluation, leader
from charmed_slurm_slurmctld_interface import (
    AUTH_KEY_LABEL,
    SlurmctldConnectedEvent,
    SlurmctldDisconnectedEvent,
    SlurmctldProvider,
    SlurmctldReadyEvent,
    SlurmctldRequirer,
    controller_ready,
    encoder,
)
from slurmutils import Partition

_REQUIRED_APP_DATA = {
    "auth_secret_id": lambda value: value != '""',
    "controllers": lambda value: value != "[]",
}


def _slurmd_app_data_validator(data: ops.RelationDataContent) -> bool:
    """Validate data sent by `slurmctld` stored in the `slurmd` integration."""
    return all(validate(data[k]) for k, validate in _REQUIRED_APP_DATA.items())


@dataclass(frozen=True)
class ComputeData:
    """Data provided by the Slurm compute service, `slurmd`."""

    partition: Partition

    def __post_init__(self) -> None:  # noqa D105
        # If `partition` is determined to be a built-in dictionary object when deserializing
        # integration data, the `partition` field will be automatically parsed into a
        # `Partition` object.
        if isinstance(self.partition, dict):
            object.__setattr__(self, "partition", Partition(self.partition))


def partition_ready(charm: ops.CharmBase) -> ConditionEvaluation:
    """Check if compute - `slurmd` - data is available.

    Notes:
        - This condition check requires that the charm has a public `slurmd`
          attribute that has a public `is_ready` method.
    """
    ready = charm.slurmd.is_ready()  # type: ignore
    return ConditionEvaluation(ready, "Waiting for partition data" if not ready else "")


class SlurmdConnectedEvent(ops.RelationEvent):
    """Event emitted when a `slurmd` application is connected to `slurmctld`."""


class SlurmdReadyEvent(ops.RelationEvent):
    """Event emitted when the primary `slurmd` unit is ready.

    Notes:
        The `slurmd` application is ready once the leader unit is fully initialized
        and able to share the partition configuration information required by the
        Slurm controller, `slurmctld`.
    """


class SlurmdDisconnectedEvent(ops.RelationEvent):
    """Event emitted when the `slurmd` application is disconnected from `slurmctld`."""


class _SlurmdRequirerEvents(ops.ObjectEvents):
    """`slurmd` requirer events."""

    slurmd_connected = ops.EventSource(SlurmdConnectedEvent)
    slurmd_ready = ops.EventSource(SlurmdReadyEvent)
    slurmd_disconnected = ops.EventSource(SlurmdDisconnectedEvent)


class SlurmdProvider(SlurmctldRequirer):
    """Integration interface implementation for `slurmd` service providers.

    This interface should be used on `slurmd` units to retrieve controller data
    from the `slurmctld` application leader.

    Notes:
        - Only the leading `slurmd` unit can handle when the integration with
          `slurmctld` is created.
    """

    def __init__(self, charm: ops.CharmBase, /, integration_name: str) -> None:
        super().__init__(
            charm,
            integration_name,
            required_app_data=set(_REQUIRED_APP_DATA),
            app_data_validator=_slurmd_app_data_validator,
        )

    @leader
    def _on_relation_created(self, event: ops.RelationCreatedEvent) -> None:
        super()._on_relation_created(event)

    @leader
    def set_compute_data(self, data: ComputeData, /, integration_id: int | None = None) -> None:
        """Set compute data in the `slurmd` application databag.

        Args:
            data: Compute data to set on an integrations' application databag.
            integration_id:
                ID of integration to update. If no integration ID is passed,
                all integrations will be updated.

        Warnings:
            - Only the `slurmd` application leader can set compute configuration data.
        """
        self._save_integration_data(data, self.app, integration_id, encoder=encoder)


class SlurmdRequirer(SlurmctldProvider):
    """Integration interface implementation for `slurmd` service requirers.

    This interface should be used on the `slurmctld` application leader to
    enlist new `slurmd` partitions, and managed the partition configuration.
    """

    on = _SlurmdRequirerEvents()  # type: ignore

    def __init__(self, charm: ops.CharmBase, /, integration_name: str) -> None:
        super().__init__(charm, integration_name, required_app_data={"partition"})
        self.framework.observe(
            self.charm.on[self._integration_name].relation_created, self._on_relation_created
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
        """Handle when a `slurmd` application is connected to `slurmctld`."""
        self.on.slurmd_connected.emit(event.relation)

    @leader
    def _on_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Handle when data from the `slurmd` application leader is ready."""
        if not event.relation.data.get(event.relation.app):
            return
        self.on.slurmd_ready.emit(event.relation)

    @leader
    def _on_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle when a `slurmd` application is disconnected from `slurmctld`."""
        if self._stored.unit_departing:
            return
        super()._on_relation_broken(event)
        self.on.slurmd_disconnected.emit(event.relation)

    def get_compute_data(self, integration_id: int | None = None) -> ComputeData:
        """Get compute data from the `slurmd` application databag.

        Args:
            integration_id: ID of integration to pull compute data from.
        """
        return self._load_integration_data(ComputeData, integration_id=integration_id).pop()
