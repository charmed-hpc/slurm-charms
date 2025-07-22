# Copyright 2025 Vantage Compute Corporation
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

import logging
from dataclasses import dataclass

import ops
from hpc_libs.interfaces.base import Interface
from hpc_libs.utils import leader, plog

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ControllerPeerAppData:
    """Data provided by the primary/leader Slurm controller, `slurmctld`.

    Attributes:
        cluster_name: The unique name of this cluster.

    Warnings:
        - `cluster_name` can only be set when the peer integration is created. The cluster name
           becomes permanent after the `SlurmctldPeerConnectedEvent` is handled.
    """

    cluster_name: str = ""


class SlurmctldPeerConnectedEvent(ops.RelationEvent):
    """Event emitted when `slurmctld` is connected to the peer integration."""


class _SlurmctldPeerEvents(ops.CharmEvents):
    """`slurmctld` peer events."""

    slurmctld_peer_connected = ops.EventSource(SlurmctldPeerConnectedEvent)


class SlurmctldPeer(Interface):
    """Integration interface implementation for `slurmctld` peers."""

    on = _SlurmctldPeerEvents()  # type: ignore

    def __init__(self, charm: ops.CharmBase, integration_name: str) -> None:
        super().__init__(charm, integration_name)

        self.charm.framework.observe(
            self.charm.on[self._integration_name].relation_created,
            self._on_relation_created,
        )

    @leader
    def _on_relation_created(self, event: ops.RelationCreatedEvent) -> None:
        """Handle when `slurmctld` peer integration is first established."""
        self.on.slurmctld_peer_connected.emit(event.relation)

    @leader
    def set_controller_peer_app_data(self, data: ControllerPeerAppData, /) -> None:
        """Set the controller peer data in the `slurmctld-peer` application databag.

        Args:
            data: Controller peer data to set in the peer integration's application databag.

        Warnings:
            - Only the `slurmctld` application leader can set controller peer app data.
        """
        integration = self.get_integration()
        if not integration:
            _logger.info(
                "`%s` integration not connected. not setting application data",
                self._integration_name,
            )
            return

        _logger.info(
            "`%s` integration is connected. setting application data",
            self._integration_name,
        )
        _logger.debug("`%s` application data:\n%s", self._integration_name, plog(data))
        integration.save(data, self.app)

    def get_controller_peer_app_data(self) -> ControllerPeerAppData | None:
        """Get controller peer from the `slurmctld-peer` application databag."""
        integration = self.get_integration()
        if not integration:
            _logger.info(
                "`%s` integration is not connected. no application data to retrieve",
                self._integration_name,
            )
            return None

        _logger.info(
            "`%s` integration is connected. retrieving application data",
            self._integration_name,
        )
        return integration.load(ControllerPeerAppData, integration.app)

    @property
    def cluster_name(self) -> str | None:
        """Get the unique cluster name from the application integration data."""
        if data := self.get_controller_peer_app_data():
            return data.cluster_name
        else:
            return None

    @cluster_name.setter
    @leader
    def cluster_name(self, value: str) -> None:
        self.set_controller_peer_app_data(ControllerPeerAppData(cluster_name=value))
