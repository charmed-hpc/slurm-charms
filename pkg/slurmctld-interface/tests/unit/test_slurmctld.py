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

"""Unit tests for the `slurmctld` integration interface implementation."""

import json
from collections import defaultdict

import ops
import pytest
from charmed_hpc_libs.ops.conditions import refresh, wait_unless
from charmed_slurm_slurmctld_interface import (
    ControllerData,
    SlurmctldConnectedEvent,
    SlurmctldDisconnectedEvent,
    SlurmctldProvider,
    SlurmctldReadyEvent,
    SlurmctldRequirer,
    controller_ready,
)
from ops import testing
from slurmutils import SlurmConfig

SLURMCTLD_INTEGRATION_NAME = "slurmctld"
EXAMPLE_AUTH_KEY = "xyz123=="
EXAMPLE_JWT_KEY = "abc987||"
EXAMPLE_CONTROLLERS = ["127.0.0.1", "127.0.1.1"]
EXAMPLE_SLURM_CONFIG = {
    "slurm.conf": SlurmConfig(
        clustername="charmed-hpc",
        slurmctldhost=EXAMPLE_CONTROLLERS,
    ),
}


class MockSlurmctldProviderCharm(ops.CharmBase):
    """Mock `slurmctld` provider charm."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmctld = SlurmctldProvider(self, SLURMCTLD_INTEGRATION_NAME)

        framework.observe(
            self.on[SLURMCTLD_INTEGRATION_NAME].relation_created,
            self._on_relation_created,
        )

    def _on_relation_created(self, event: ops.RelationCreatedEvent) -> None:
        self.slurmctld.set_controller_data(
            ControllerData(
                auth_key=EXAMPLE_AUTH_KEY,
                jwt_key=EXAMPLE_JWT_KEY,
                controllers=EXAMPLE_CONTROLLERS,
                slurmconfig=EXAMPLE_SLURM_CONFIG,
            ),
            integration_id=event.relation.id,
        )


class MockSlurmctldRequirerCharm(ops.CharmBase):
    """Mock `slurmctld` requirer charm."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmctld = SlurmctldRequirer(self, SLURMCTLD_INTEGRATION_NAME)

        framework.observe(
            self.slurmctld.on.slurmctld_connected,
            self._on_slurmctld_connected,
        )
        framework.observe(
            self.slurmctld.on.slurmctld_ready,
            self._on_slurmctld_ready,
        )
        framework.observe(
            self.slurmctld.on.slurmctld_disconnected,
            self._on_slurmctld_disconnected,
        )

    def _on_slurmctld_connected(self, event: SlurmctldConnectedEvent) -> None: ...

    @refresh(hook=None)
    @wait_unless(controller_ready)
    def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
        data = self.slurmctld.get_controller_data(integration_id=event.relation.id)
        assert data.auth_key == EXAMPLE_AUTH_KEY
        assert data.jwt_key == EXAMPLE_JWT_KEY
        assert data.controllers == EXAMPLE_CONTROLLERS

    def _on_slurmctld_disconnected(self, event: SlurmctldDisconnectedEvent) -> None: ...


@pytest.fixture(scope="function")
def provider_ctx() -> testing.Context[MockSlurmctldProviderCharm]:
    return testing.Context(
        MockSlurmctldProviderCharm,
        meta={
            "name": "slurmctld-provider",
            "provides": {SLURMCTLD_INTEGRATION_NAME: {"interface": "slurmctld"}},
        },
    )


@pytest.fixture(scope="function")
def requirer_ctx() -> testing.Context[MockSlurmctldRequirerCharm]:
    return testing.Context(
        MockSlurmctldRequirerCharm,
        meta={
            "name": "slurmctld-requirer",
            "requires": {SLURMCTLD_INTEGRATION_NAME: {"interface": "slurmctld"}},
        },
    )


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSlurmctldInterface:
    """Unit tests for the `slurmctld` integration interface implementation."""

    # Test provider-side of the `slurmctld` interface.

    def test_provider_set_controller_data(self, provider_ctx, leader) -> None:
        """Test that the `slurmctld` provider correctly sets controller data."""
        slurmctld_integration_id = 1
        slurmctld_integration = testing.Relation(
            endpoint=SLURMCTLD_INTEGRATION_NAME,
            interface="slurmctld",
            id=slurmctld_integration_id,
            remote_app_name="slurmctld-requirer",
        )

        state = provider_ctx.run(
            provider_ctx.on.relation_created(slurmctld_integration),
            testing.State(leader=leader, relations={slurmctld_integration}),
        )

        integration = state.get_relation(slurmctld_integration_id)
        if leader:
            # Verify that auth_key and jwt_key are redacted in the integration data.
            assert integration.local_app_data["auth_key"] == '"***"'
            assert integration.local_app_data["jwt_key"] == '"***"'

            # Verify that secret IDs have been set (non-empty).
            assert integration.local_app_data["auth_key_id"] != '""'
            assert integration.local_app_data["jwt_key_id"] != '""'

            # Verify controllers and slurmconfig are set correctly.
            assert json.loads(integration.local_app_data["controllers"]) == EXAMPLE_CONTROLLERS
            assert "slurmconfig" in integration.local_app_data
        else:
            # Non-leader units must not write to the application databag.
            assert integration.local_app_data == {}

    @pytest.mark.parametrize(
        "auth_key,jwt_key",
        (
            pytest.param(EXAMPLE_AUTH_KEY, "", id="auth-key-only"),
            pytest.param("", EXAMPLE_JWT_KEY, id="jwt-key-only"),
            pytest.param(EXAMPLE_AUTH_KEY, EXAMPLE_JWT_KEY, id="both-keys"),
            pytest.param("", "", id="no-keys"),
        ),
    )
    def test_provider_set_controller_data_secret_handling(
        self, provider_ctx, leader, auth_key, jwt_key
    ) -> None:
        """Test that `set_controller_data` correctly creates secrets only for non-empty keys."""
        slurmctld_integration_id = 1
        slurmctld_integration = testing.Relation(
            endpoint=SLURMCTLD_INTEGRATION_NAME,
            interface="slurmctld",
            id=slurmctld_integration_id,
            remote_app_name="slurmctld-requirer",
        )

        # Use a custom provider charm that sets specific auth/jwt key combinations.
        class _MockCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework) -> None:
                super().__init__(framework)
                self.slurmctld = SlurmctldProvider(self, SLURMCTLD_INTEGRATION_NAME)
                framework.observe(
                    self.on[SLURMCTLD_INTEGRATION_NAME].relation_created,
                    self._on_relation_created,
                )

            def _on_relation_created(self, event: ops.RelationCreatedEvent) -> None:
                self.slurmctld.set_controller_data(
                    ControllerData(auth_key=auth_key, jwt_key=jwt_key),
                    integration_id=event.relation.id,
                )

        ctx = testing.Context(
            _MockCharm,
            meta={
                "name": "slurmctld-provider",
                "provides": {SLURMCTLD_INTEGRATION_NAME: {"interface": "slurmctld"}},
            },
        )

        state = ctx.run(
            ctx.on.relation_created(slurmctld_integration),
            testing.State(leader=leader, relations={slurmctld_integration}),
        )

        if leader:
            integration = state.get_relation(slurmctld_integration_id)

            # auth_key and jwt_key are always redacted after set_controller_data.
            assert integration.local_app_data["auth_key"] == '"***"'
            assert integration.local_app_data["jwt_key"] == '"***"'

            # Secret IDs are set only when the key was non-empty.
            if auth_key:
                assert integration.local_app_data["auth_key_id"] != '""'
            else:
                assert integration.local_app_data["auth_key_id"] == '""'

            if jwt_key:
                assert integration.local_app_data["jwt_key_id"] != '""'
            else:
                assert integration.local_app_data["jwt_key_id"] == '""'

    def test_provider_on_relation_broken_revokes_secrets(self, provider_ctx, leader) -> None:
        """Test that the `slurmctld` provider revokes secrets when a relation is broken."""
        auth_key_secret = testing.Secret(
            tracked_content={"key": EXAMPLE_AUTH_KEY},
            label="integration-1-auth-key-secret",
            owner="app",
        )
        jwt_key_secret = testing.Secret(
            tracked_content={"key": EXAMPLE_JWT_KEY},
            label="integration-1-jwt-key-secret",
            owner="app",
        )

        slurmctld_integration_id = 1
        slurmctld_integration = testing.Relation(
            endpoint=SLURMCTLD_INTEGRATION_NAME,
            interface="slurmctld",
            id=slurmctld_integration_id,
            remote_app_name="slurmctld-requirer",
            local_app_data={
                "auth_key": '"***"',
                "auth_key_id": json.dumps(auth_key_secret.id),
                "jwt_key": '"***"',
                "jwt_key_id": json.dumps(jwt_key_secret.id),
            },
        )

        state = provider_ctx.run(
            provider_ctx.on.relation_broken(slurmctld_integration),
            testing.State(
                leader=leader,
                relations={slurmctld_integration},
                secrets={auth_key_secret, jwt_key_secret},
            ),
        )

        if leader:
            # Both secrets should have been removed by the leader.
            assert auth_key_secret.id not in {s.id for s in state.secrets}
            assert jwt_key_secret.id not in {s.id for s in state.secrets}

    # Test requirer-side of the `slurmctld` interface.

    def test_requirer_on_slurmctld_connected_event(self, requirer_ctx, leader) -> None:
        """Test that `SlurmctldConnectedEvent` is emitted when a relation is created."""
        slurmctld_integration_id = 1
        slurmctld_integration = testing.Relation(
            endpoint=SLURMCTLD_INTEGRATION_NAME,
            interface="slurmctld",
            id=slurmctld_integration_id,
            remote_app_name="slurmctld-provider",
        )

        requirer_ctx.run(
            requirer_ctx.on.relation_created(slurmctld_integration),
            testing.State(leader=leader, relations={slurmctld_integration}),
        )

        # `SlurmctldConnectedEvent` is always emitted for all units (no `@leader` guard).
        occurred = defaultdict(lambda: 0)
        for event in requirer_ctx.emitted_events:
            occurred[type(event)] += 1

        assert occurred[SlurmctldConnectedEvent] == 1

    @pytest.mark.parametrize(
        "ready",
        (
            pytest.param(True, id="ready"),
            pytest.param(False, id="not ready"),
        ),
    )
    def test_requirer_on_slurmctld_ready_event(self, requirer_ctx, leader, ready) -> None:
        """Test that the `slurmctld` requirer waits for controller data to be available."""
        auth_key_secret = testing.Secret(tracked_content={"key": EXAMPLE_AUTH_KEY})
        jwt_key_secret = testing.Secret(tracked_content={"key": EXAMPLE_JWT_KEY})

        slurmctld_integration_id = 1
        slurmctld_integration = testing.Relation(
            endpoint=SLURMCTLD_INTEGRATION_NAME,
            interface="slurmctld",
            id=slurmctld_integration_id,
            remote_app_name="slurmctld-provider",
            # Simulate `SlurmctldRequirer` treating the remote app data as the controller data.
            # When ready, populate with all required fields; when not ready, leave app data empty.
            remote_app_data=(
                {
                    "auth_key": '"***"',
                    "auth_key_id": json.dumps(auth_key_secret.id),
                    "jwt_key": '"***"',
                    "jwt_key_id": json.dumps(jwt_key_secret.id),
                    "controllers": json.dumps(EXAMPLE_CONTROLLERS),
                }
                if ready
                else {}
            ),
        )

        state = requirer_ctx.run(
            requirer_ctx.on.relation_changed(slurmctld_integration),
            testing.State(
                leader=leader,
                relations={slurmctld_integration},
                secrets={auth_key_secret, jwt_key_secret},
            ),
        )

        if ready:
            # `SlurmctldReadyEvent` is emitted for all units when remote app data is present.
            occurred = defaultdict(lambda: 0)
            for event in requirer_ctx.emitted_events:
                occurred[type(event)] += 1

            assert occurred[SlurmctldReadyEvent] == 1

            # The `@wait_unless(controller_ready)` guard defers if `is_ready()` returns False.
            # Since we set all fields, `is_ready()` is True and no deferral happens.
            assert len(state.deferred) == 0
            assert state.unit_status != ops.WaitingStatus("Waiting for controller data")
        else:
            # When remote app data is absent the `relation_changed` handler in
            # `SlurmctldRequirer._on_relation_changed` bails early and emits nothing.
            assert not any(
                isinstance(event, SlurmctldReadyEvent) for event in requirer_ctx.emitted_events
            )
            assert len(state.deferred) == 0

    def test_requirer_on_slurmctld_disconnected_event(self, requirer_ctx, leader) -> None:
        """Test that `SlurmctldDisconnectedEvent` is emitted when a relation is broken."""
        slurmctld_integration_id = 1
        slurmctld_integration = testing.Relation(
            endpoint=SLURMCTLD_INTEGRATION_NAME,
            interface="slurmctld",
            id=slurmctld_integration_id,
            remote_app_name="slurmctld-provider",
        )

        requirer_ctx.run(
            requirer_ctx.on.relation_broken(slurmctld_integration),
            testing.State(leader=leader, relations={slurmctld_integration}),
        )

        # `SlurmctldDisconnectedEvent` is emitted for all units (no `@leader` guard).
        occurred = defaultdict(lambda: 0)
        for event in requirer_ctx.emitted_events:
            occurred[type(event)] += 1

        assert occurred[SlurmctldDisconnectedEvent] == 1

    def test_requirer_get_controller_data(self, requirer_ctx, leader) -> None:
        """Test that `get_controller_data` correctly retrieves and decrypts secret values."""
        auth_key_secret = testing.Secret(tracked_content={"key": EXAMPLE_AUTH_KEY})
        jwt_key_secret = testing.Secret(tracked_content={"key": EXAMPLE_JWT_KEY})

        slurmctld_integration_id = 1
        slurmctld_integration = testing.Relation(
            endpoint=SLURMCTLD_INTEGRATION_NAME,
            interface="slurmctld",
            id=slurmctld_integration_id,
            remote_app_name="slurmctld-provider",
            remote_app_data={
                "auth_key": '"***"',
                "auth_key_id": json.dumps(auth_key_secret.id),
                "jwt_key": '"***"',
                "jwt_key_id": json.dumps(jwt_key_secret.id),
                "controllers": json.dumps(EXAMPLE_CONTROLLERS),
                "slurmconfig": json.dumps({k: v.dict() for k, v in EXAMPLE_SLURM_CONFIG.items()}),
            },
        )

        # Use a simple requirer charm that stores the retrieved data for verification.
        retrieved: list[ControllerData] = []

        class _MockCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework) -> None:
                super().__init__(framework)
                self.slurmctld = SlurmctldRequirer(self, SLURMCTLD_INTEGRATION_NAME)
                framework.observe(self.slurmctld.on.slurmctld_ready, self._on_slurmctld_ready)

            def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
                retrieved.append(
                    self.slurmctld.get_controller_data(integration_id=event.relation.id)
                )

        ctx = testing.Context(
            _MockCharm,
            meta={
                "name": "slurmctld-requirer",
                "requires": {SLURMCTLD_INTEGRATION_NAME: {"interface": "slurmctld"}},
            },
        )

        ctx.run(
            ctx.on.relation_changed(slurmctld_integration),
            testing.State(
                leader=leader,
                relations={slurmctld_integration},
                secrets={auth_key_secret, jwt_key_secret},
            ),
        )

        assert len(retrieved) == 1
        data = retrieved[0]

        # Secrets should be decrypted from their Juju secret backing store.
        assert data.auth_key == EXAMPLE_AUTH_KEY
        assert data.jwt_key == EXAMPLE_JWT_KEY

        # Plain fields should be deserialized correctly.
        assert data.controllers == EXAMPLE_CONTROLLERS
        assert "slurm.conf" in data.slurmconfig
        assert data.slurmconfig["slurm.conf"].dict() == EXAMPLE_SLURM_CONFIG["slurm.conf"].dict()
