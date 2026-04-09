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

"""Integration interface implementation for the `slurmctld` interface."""

__all__ = [
    "ControllerData",
    "SlurmctldConnectedEvent",
    "SlurmctldDisconnectedEvent",
    "SlurmctldProvider",
    "SlurmctldReadyEvent",
    "SlurmctldRequirer",
    "controller_ready",
    "encoder",
]

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from string import Template
from typing import Any

import ops
from charmed_hpc_libs.interfaces import Interface
from charmed_hpc_libs.ops import ConditionEvaluation, leader, load_secret, update_secret
from slurmutils import Model, SlurmConfig

_logger = logging.getLogger(__name__)

AUTH_KEY_TEMPLATE_LABEL = Template("integration-$id-auth-key-secret")
JWT_KEY_TEMPLATE_LABEL = Template("integration-$id-jwt-key-secret")


class _SlurmJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for working with `slurmutils` models."""

    def default(self, o: Any) -> Any:
        if isinstance(o, Model):
            return o.dict()

        return super().default(o)


def encoder(value: Any) -> str:
    """Encode Slurm integration data."""
    return json.dumps(value, cls=_SlurmJSONEncoder)


@dataclass(frozen=True)
class ControllerData:
    """Data provided by the Slurm controller service, `slurmctld`.

    Attributes:
        auth_key: Base64-encoded string representing the `auth/slurm` key.
        auth_key_id: ID of the `auth/slurm` key Juju secret for this integration instance.
        controllers:
            List of controller addresses for that can be used by Slurm services
            for contacting the `slurmctld` application. The first entry in the list is the
            primary `slurmctld` service. Other entries are failovers.
        jwt_key: Base64-encoded string representing the Slurm JWT key.
        jwt_key_id: ID of the Slurm JWT key Juju secret for this integration instance.
        slurmconfig: Mapping containing the `slurm.conf` and other included configuration files.

    Notes:
        - `sackd` requires:         `auth_key_id`, `controllers`
        - `slurmd` requires:        `auth_key_id`, `controllers`
        - `slurmdbd` requires:      `auth_key_id`, `jwt_key_id`
        - `slurmrestd` requires:    `auth_key_id`, `slurmconfig`
    """

    auth_key: str = ""
    auth_key_id: str = ""
    controllers: list[str] = field(default_factory=list)
    jwt_key: str = ""
    jwt_key_id: str = ""
    slurmconfig: dict[str, SlurmConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:  # noqa D105
        # If the value of a key in `slurmconfig` is determined to be a built-in dictionary
        # object when deserializing integration data, the dictionary value will be automatically
        # parsed into a `SlurmConfig` object.
        for k, v in self.slurmconfig.items():
            if isinstance(v, dict):
                self.slurmconfig[k] = SlurmConfig(v)


def controller_ready(charm: ops.CharmBase) -> ConditionEvaluation:
    """Check if controller - `slurmctld` - data is available.

    Notes:
        - This condition check requires that the charm has a public `slurmctld`
          attribute that has a public `is_ready` method.
    """
    ready = charm.slurmctld.is_ready()  # type: ignore
    return ConditionEvaluation(ready, "Waiting for controller data" if not ready else "")


class SlurmctldConnectedEvent(ops.RelationEvent):
    """Event emitted when `slurmctld` is connected to a Slurm-related application."""


class SlurmctldReadyEvent(ops.RelationEvent):
    """Event emitted when the primary `slurmctld` service is ready.

    Notes:
        The `slurmctld` application is ready once it is fully initialized and able to share
        the configuration information required by other Slurm services such as `slurmd`.
    """


class SlurmctldDisconnectedEvent(ops.RelationEvent):
    """Event emitted when `slurmctld` is disconnected from a Slurm-related application."""


class _SlurmctldRequirerEvents(ops.ObjectEvents):
    """`slurmctld` requirer events."""

    slurmctld_connected = ops.EventSource(SlurmctldConnectedEvent)
    slurmctld_ready = ops.EventSource(SlurmctldReadyEvent)
    slurmctld_disconnected = ops.EventSource(SlurmctldDisconnectedEvent)


class SlurmctldProvider(Interface):
    """Base interface for `slurmctld` providers to consume Slurm service data.

    Notes:
        - This interface is not intended to be used directly. Child interfaces should inherit
          from this interface so that they can provide `slurmctld` data and consume configuration
          provided by other Slurm services such as `slurmd` or `slurmdbd`.
    """

    def __init__(
        self,
        charm: ops.CharmBase,
        /,
        integration_name: str,
        *,
        required_app_data: Iterable[str] | None = None,
        app_data_validator: Callable[[ops.RelationDataContent], bool] | None = None,
    ) -> None:
        super().__init__(
            charm,
            integration_name,
            required_app_data=required_app_data,
            app_data_validator=app_data_validator,
        )

        self.framework.observe(
            self.charm.on[self._integration_name].relation_broken,
            self._on_relation_broken,
        )

    @leader
    def _on_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Revoke the departing application's access to Slurm secrets."""
        if self._stored.unit_departing:
            return

        if auth_secret := load_secret(
            self.charm,
            label=AUTH_KEY_TEMPLATE_LABEL.substitute(id=event.relation.id),
        ):
            auth_secret.remove_all_revisions()

        if jwt_secret := load_secret(
            self.charm,
            label=JWT_KEY_TEMPLATE_LABEL.substitute(id=event.relation.id),
        ):
            jwt_secret.remove_all_revisions()

    @leader
    def set_controller_data(
        self, data: ControllerData, /, integration_id: int | None = None
    ) -> None:
        """Set `slurmctld` controller data for Slurm services on application databag.

        Args:
            data: Controller data to set on an integrations' application databag.
            integration_id:
                (Optional) ID of integration to update. If no integration id is passed,
                all integrations will be updated. This argument must be set for a
                integration to be granted access to the `auth_key` and `jwt_key` secrets.
        """
        if integration_id is not None:
            integration = self.get_integration(integration_id)

            if data.auth_key:
                secret = update_secret(
                    self.charm,
                    AUTH_KEY_TEMPLATE_LABEL.substitute(id=integration_id),
                    {"key": data.auth_key},
                )
                secret.grant(integration)
                object.__setattr__(data, "auth_key_id", secret.id)

            if data.jwt_key:
                secret = update_secret(
                    self.charm,
                    JWT_KEY_TEMPLATE_LABEL.substitute(id=integration_id),
                    {"key": data.jwt_key},
                )
                secret.grant(integration)
                object.__setattr__(data, "jwt_key_id", secret.id)

        # Redact secrets. "***" indicates that an interface did not unlock a secret.
        object.__setattr__(data, "auth_key", "***")
        object.__setattr__(data, "jwt_key", "***")

        self._save_integration_data(data, self.app, integration_id, encoder=encoder)


class SlurmctldRequirer(Interface):
    """Base interface for applications to retrieve data provided by `slurmctld`.

    Notes:
        - This interface is not intended to be used directly. Child interfaces should inherit
          from this interface to consume data from the Slurm controller `slurmctld` and provide
          necessary configuration information to `slurmctld`.
    """

    on = _SlurmctldRequirerEvents()  # type: ignore

    def __init__(
        self,
        charm: ops.CharmBase,
        /,
        integration_name: str,
        *,
        required_app_data: Iterable[str] | None = None,
        app_data_validator: Callable[[ops.RelationDataContent], bool] | None = None,
    ) -> None:
        super().__init__(
            charm,
            integration_name,
            required_app_data=required_app_data,
            app_data_validator=app_data_validator,
        )

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

    def _on_relation_created(self, event: ops.RelationCreatedEvent) -> None:
        """Handle when `slurmctld` is connected to an application."""
        self.on.slurmctld_connected.emit(event.relation)

    def _on_relation_changed(self, event: ops.RelationChangedEvent) -> None:
        """Handle when data from the primary `slurmctld` unit is ready."""
        if not event.relation.data.get(event.app):
            return

        self.on.slurmctld_ready.emit(event.relation)

    def _on_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
        """Handle when `slurmctld` is disconnected from an application."""
        if self._stored.unit_departing:
            return

        self.on.slurmctld_disconnected.emit(event.relation)

    def get_controller_data(self, integration_id: int | None = None) -> ControllerData:
        """Get controller data from the `slurmctld` application databag."""
        data = self._load_integration_data(ControllerData, integration_id=integration_id).pop()
        if data.auth_key_id:
            auth_key = self.charm.model.get_secret(id=data.auth_key_id)
            object.__setattr__(data, "auth_key", auth_key.get_content().get("key"))
        if data.jwt_key_id:
            jwt_key = self.charm.model.get_secret(id=data.jwt_key_id)
            object.__setattr__(data, "jwt_key", jwt_key.get_content().get("key"))

        return data
