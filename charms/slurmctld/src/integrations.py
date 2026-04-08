# Copyright 2025-2026 Vantage Compute Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Integration interface implementation for `slurmctld-peer` interface."""

__all__ = [
    "ControllerPeerAppData",
    "SlurmctldPeerConnectedEvent",
    "SlurmctldPeer",
]

import json
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import ops
from charmed_hpc_libs.interfaces import Interface
from charmed_hpc_libs.ops import leader
from state import all_units_observed

if TYPE_CHECKING:
    from charm import SlurmctldCharm

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ControllerPeerAppData:
    """Data provided by the primary/leader Slurm controller, `slurmctld`.

    Attributes:
        cluster_name: The unique name of this cluster.
        restart_signal: A nonce to indicate all controllers should restart `slurmctld.service`.

    Warnings:
        - The cluster name should only be set once during the entire lifetime of
          a deployed `slurmctld` application. If the cluster name is overwritten
          after being set, this will unrecoverably corrupt the controller's
          `StateSaveLocation` data.
    """

    cluster_name: str = ""
    restart_signal: str = ""


@dataclass(frozen=True)
class ControllerPeerUnitData:
    """Data provided by each Slurm controller (`slurmctld`) unit.

    Attributes:
        hostname: The hostname for this unit.
    """

    hostname: str = ""


class SlurmctldPeerConnectedEvent(ops.RelationEvent):
    """Event emitted when `slurmctld` is connected to the peer integration."""


class SlurmctldPeerJoinedEvent(ops.RelationEvent):
    """Emitted when a new `slurmctld` controller instance joins the peer integration."""


class SlurmctldPeerDepartedEvent(ops.RelationEvent):
    """Emitted when a `slurmctld` controller leaves the peer integration."""


def _unit_data_decoder(value: str) -> str:
    """Decode integration unit databag data.

    The default encoder for `ops.Relation.load()` is `json.loads()` which incorrectly tries to
    decode IPv4 addresses as float values. This decoder circumvents this error by quoting unquoted
    values to convert them to strings.

    The unit databag, by default, contains IP addresses such as the `ingress-address` for the unit.
    The default `json.loads()` decoder causes an `json.decoder.JSONDecodeError: Extra data` error
    when attempting to decode these values.
    """
    if not (value.startswith('"') and value.endswith('"')):
        value = f'"{value}"'
    return json.loads(value)


class _SlurmctldPeerEvents(ops.CharmEvents):
    """`slurmctld` peer events."""

    slurmctld_peer_connected = ops.EventSource(SlurmctldPeerConnectedEvent)
    slurmctld_peer_joined = ops.EventSource(SlurmctldPeerJoinedEvent)
    slurmctld_peer_departed = ops.EventSource(SlurmctldPeerDepartedEvent)


class SlurmctldPeer(Interface):
    """Integration interface implementation for `slurmctld` peers."""

    on = _SlurmctldPeerEvents()  # type: ignore
    _stored = ops.StoredState()
    charm: "SlurmctldCharm"

    def __init__(self, charm: "SlurmctldCharm", integration_name: str) -> None:
        super().__init__(charm, integration_name)

        self._stored.set_default(
            last_restart_signal=str(),  # nonce to indicate slurmctld service restart required
        )

        self.charm.framework.observe(
            self.charm.on[self._integration_name].relation_created,
            self._on_relation_created,
        )
        self.charm.framework.observe(
            self.charm.on[self._integration_name].relation_changed,
            self._on_relation_changed,
        )
        self.framework.observe(
            self.charm.on[self._integration_name].relation_departed,
            self._on_relation_departed,
        )

    def _on_relation_created(self, event: ops.RelationCreatedEvent) -> None:
        """Handle when `slurmctld` peer integration is first established."""
        # Each slurmctld instance must set its hostname in its own unit databag for the leader to
        # gather to assemble all SlurmctldHost entries in slurm.conf.
        # Set here rather than the emitted event handler to ensure the hostname is available before
        # the `start` hook runs.
        self.update_controller_peer_unit_data(hostname=self.charm.slurmctld.hostname)

        self.on.slurmctld_peer_connected.emit(event.relation)

    def _on_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Handle when `slurmctld` peer integration data is changed."""
        data = self.get_controller_peer_app_data()
        if not data:
            _logger.debug("no application data set in peer relation. ignoring change event")
            return

        # A slurmctld.service restart signal has been sent by the leader.
        if data.restart_signal != self._stored.last_restart_signal:
            _logger.debug("restart signal found. restarting slurmctld")
            self._stored.last_restart_signal = data.restart_signal

            # Leader already restarted its service when reconfiguring
            if not self.unit.is_leader():
                # Emits if a start event is not already in the defer queue
                self.charm.on.start.emit()
            return

        # Unit(s) have joined the relation.
        # Fire once the leader unit has observed relation-joined for all units
        if self.unit.is_leader() and all_units_observed(self.charm).ok:
            self.on.slurmctld_peer_joined.emit(event.relation)
            return

    def _on_relation_departed(self, event: ops.RelationDepartedEvent) -> None:
        """Handle when a `slurmctld` unit departs the peer relation."""
        # Fire only once the leader unit has seen the last departing unit leave
        if self.unit.is_leader() and all_units_observed(self.charm).ok:
            if event.departing_unit == self.unit:
                _logger.debug(
                    "leader is departing. next elected leader will refresh controller config"
                )
                return

            self.on.slurmctld_peer_departed.emit(event.relation)

    def get_controller_peer_app_data(self) -> ControllerPeerAppData | None:
        """Get controller peer from the `slurmctld-peer` application databag."""
        return self._get_peer_data(self.app, ControllerPeerAppData)

    def get_controller_peer_unit_data(self, unit: ops.Unit) -> ControllerPeerUnitData | None:
        """Get controller peer data from a `slurmctld-peer` unit databag.

        Args:
            unit: Unit to get the data from.

        Returns:
            The controller peer data for the given unit, or `None` if no data is set.
        """
        return self._get_peer_data(unit, ControllerPeerUnitData, _unit_data_decoder)

    def get_controllers(self) -> set[str]:
        """Return controller hostnames from the peer relation.

        Always includes the hostname of this unit, even when the peer relation is not established.
        This ensures a valid controller is returned when integrations with other applications, such
        as slurmd or sackd, occur first.
        """
        # Need self.charm.slurmctld.hostname as getting hostname from the unit databag fails if peer
        # relation is not yet established
        controllers = {self.charm.slurmctld.hostname}

        integration = self.get_integration()
        if not integration:
            _logger.debug(
                "`%s` integration is not connected. returning local controller only",
                self._integration_name,
            )
            return controllers

        for unit in integration.units:
            data = self.get_controller_peer_unit_data(unit)
            if data and data.hostname != "":
                controllers.add(data.hostname)

        _logger.debug("returning controllers: %s", controllers)
        return controllers

    @leader
    def signal_slurmctld_restart(self) -> None:
        """Add a message to the peer relation to indicate all peers should restart slurmctld.service.

        This is a workaround for `scontrol reconfigure` not instructing all slurmctld daemons to
        re-read SlurmctldHost lines from slurm.conf.
        """
        # The value written to the relation must be unique on each call.
        signal = str(uuid.uuid4())
        self.update_controller_peer_app_data(restart_signal=signal)

    @leader
    def update_controller_peer_app_data(
        self,
        *,
        cluster_name: str | None = None,
        restart_signal: str | None = None,
    ) -> None:
        """Update the controller peer data in the `slurmctld-peer` application databag.

        Args:
            cluster_name: The unique name of this cluster.
            restart_signal: A nonce to indicate all controllers should restart `slurmctld.service`.

        Warnings:
            - Only the `slurmctld` application leader can update controller peer app data.
        """
        current = self.get_controller_peer_app_data() or ControllerPeerAppData()
        data = ControllerPeerAppData(
            cluster_name=cluster_name if cluster_name is not None else current.cluster_name,
            restart_signal=(
                restart_signal if restart_signal is not None else current.restart_signal
            ),
        )
        self._set_peer_data(self.app, data)

    def update_controller_peer_unit_data(self, *, hostname: str | None = None) -> None:
        """Update the controller peer data in this unit's databag.

        Only updates fields that are not None.
        """
        current = self.get_controller_peer_unit_data(self.unit) or ControllerPeerUnitData()
        data = ControllerPeerUnitData(
            hostname=hostname if hostname is not None else current.hostname,
        )
        self._set_peer_data(self.unit, data)

    def _get_peer_data(
        self,
        target: ops.Application | ops.Unit,
        data_type: type[ControllerPeerAppData] | type[ControllerPeerUnitData],
        decoder=None,
    ) -> Any:
        """Get unit or app peer data."""
        integration = self.get_integration()
        if not integration:
            _logger.debug(
                "`%s` integration is not connected. no data to retrieve for '%s'",
                self._integration_name,
                target.name,
            )
            return None

        _logger.debug(
            "`%s` integration is connected. retrieving data for '%s'",
            self._integration_name,
            target.name,
        )

        if decoder is None:
            return integration.load(data_type, target)
        return integration.load(data_type, target, decoder=decoder)

    def _set_peer_data(
        self,
        target: ops.Application | ops.Unit,
        data: ControllerPeerAppData | ControllerPeerUnitData,
    ) -> None:
        """Set app or unit peer data."""
        integration = self.get_integration()
        if not integration:
            _logger.debug(
                "`%s` integration not connected. not setting data for '%s'",
                self._integration_name,
                target.name,
            )
            return

        _logger.debug(
            "`%s` integration is connected. setting data for '%s'",
            self._integration_name,
            target.name,
        )
        _logger.debug("`%s` data for '%s':\n%s", self._integration_name, target.name, data)
        integration.save(data, target)
