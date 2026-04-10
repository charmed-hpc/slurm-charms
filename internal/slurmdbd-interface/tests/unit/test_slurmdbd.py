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

"""Unit tests for the `slurmdbd` integration interface implementation."""

import json
from collections import defaultdict

import ops
import pytest
from charmed_hpc_libs.ops.conditions import refresh, wait_unless
from charmed_slurm_slurmctld_interface import (
    ControllerData,
    SlurmctldConnectedEvent,
    SlurmctldDisconnectedEvent,
)
from charmed_slurm_slurmdbd_interface import (
    DatabaseData,
    SlurmctldReadyEvent,
    SlurmdbdConnectedEvent,
    SlurmdbdDisconnectedEvent,
    SlurmdbdProvider,
    SlurmdbdReadyEvent,
    SlurmdbdRequirer,
    controller_ready,
    database_ready,
)
from ops import testing

SLURMDBD_INTEGRATION_NAME = "slurmdbd"
EXAMPLE_AUTH_KEY = "xyz123=="
EXAMPLE_HOSTNAME = "127.0.0.1"
EXAMPLE_JWT_KEY = "abc987||"


class MockSlurmdbdProviderCharm(ops.CharmBase):
    """Mock `slurmdbd` provider charm."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmctld = SlurmdbdProvider(self, SLURMDBD_INTEGRATION_NAME)

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

    def _on_slurmctld_connected(self, event: SlurmctldConnectedEvent) -> None:
        self.slurmctld.set_database_data(
            DatabaseData(hostname=EXAMPLE_HOSTNAME),
            integration_id=event.relation.id,
        )

    @refresh(hook=None)
    @wait_unless(controller_ready)
    def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
        data = self.slurmctld.get_controller_data(integration_id=event.relation.id)
        # Assume `remote_app_data` contains `auth_key` and `jwt_key`.
        assert data.auth_key == EXAMPLE_AUTH_KEY
        assert data.jwt_key == EXAMPLE_JWT_KEY

    def _on_slurmctld_disconnected(self, event: SlurmctldDisconnectedEvent) -> None: ...


class MockSlurmdbdRequirerCharm(ops.CharmBase):
    """Mock `slurmdbd` requirer charm."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmdbd = SlurmdbdRequirer(self, SLURMDBD_INTEGRATION_NAME)

        framework.observe(
            self.slurmdbd.on.slurmdbd_connected,
            self._on_slurmdbd_connected,
        )
        framework.observe(self.slurmdbd.on.slurmdbd_ready, self._on_slurmdbd_ready)
        framework.observe(
            self.slurmdbd.on.slurmdbd_disconnected,
            self._on_slurmdbd_disconnected,
        )

    def _on_slurmdbd_connected(self, event: SlurmdbdConnectedEvent) -> None:
        self.slurmdbd.set_controller_data(
            ControllerData(
                auth_key=EXAMPLE_AUTH_KEY,
                jwt_key=EXAMPLE_JWT_KEY,
            ),
            integration_id=event.relation.id,
        )

    @refresh(hook=None)
    @wait_unless(database_ready)
    def _on_slurmdbd_ready(self, event: SlurmdbdReadyEvent) -> None:
        data = self.slurmdbd.get_database_data(integration_id=event.relation.id)
        # Assume `remote_app_data` contains `hostname`.
        assert data.hostname == EXAMPLE_HOSTNAME

    def _on_slurmdbd_disconnected(self, event: SlurmdbdDisconnectedEvent) -> None: ...


@pytest.fixture(scope="function")
def provider_ctx() -> testing.Context[MockSlurmdbdProviderCharm]:
    return testing.Context(
        MockSlurmdbdProviderCharm,
        meta={
            "name": "slurmdbd-provider",
            "provides": {SLURMDBD_INTEGRATION_NAME: {"interface": "slurmdbd"}},
        },
    )


@pytest.fixture(scope="function")
def requirer_ctx() -> testing.Context[MockSlurmdbdRequirerCharm]:
    return testing.Context(
        MockSlurmdbdRequirerCharm,
        meta={
            "name": "slurmdbd-requirer",
            "requires": {SLURMDBD_INTEGRATION_NAME: {"interface": "slurmdbd"}},
        },
    )


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSlurmdbdInterface:
    """Unit tests for the `slurmdbd` integration interface implementation."""

    # Test provider-side of the `slurmdbd` interface.

    def test_provider_on_slurmctld_connected_event(self, provider_ctx, leader) -> None:
        """Test that the `slurmdbd` provider waits for controller data."""
        slurmdbd_integration_id = 1
        slurmdbd_integration = testing.Relation(
            endpoint=SLURMDBD_INTEGRATION_NAME,
            interface="slurmdbd",
            id=slurmdbd_integration_id,
            remote_app_name="slurmdbd-requirer",
        )

        state = provider_ctx.run(
            provider_ctx.on.relation_created(slurmdbd_integration),
            testing.State(leader=leader, relations={slurmdbd_integration}),
        )

        integration = state.get_relation(slurmdbd_integration_id)
        if leader:
            # Verify that the database leader has set database data in `local_app_data`.
            assert "hostname" in integration.local_app_data
            assert integration.local_app_data["hostname"] == f'"{EXAMPLE_HOSTNAME}"'
        else:
            # Verify that non-leader units have not set anything in `local_app_data`.
            # Non-leader `slurmdbd` units should ignore `SlurmctldConnectedEvent`.
            assert integration.local_app_data == {}
            assert not any(
                isinstance(event, SlurmctldConnectedEvent) for event in provider_ctx.emitted_events
            )

    @pytest.mark.parametrize(
        "ready",
        (
            pytest.param(True, id="ready"),
            pytest.param(False, id="not ready"),
        ),
    )
    def test_provider_on_slurmctld_ready_event(self, provider_ctx, leader, ready) -> None:
        """Test that the `slurmdbd` provider waits for controller data."""
        auth_key_secret = testing.Secret(tracked_content={"key": EXAMPLE_AUTH_KEY})
        jwt_key_secret = testing.Secret(tracked_content={"key": EXAMPLE_JWT_KEY})

        slurmdbd_integration_id = 1
        slurmdbd_integration = testing.Relation(
            endpoint=SLURMDBD_INTEGRATION_NAME,
            interface="slurmdbd",
            id=slurmdbd_integration_id,
            remote_app_name="slurmdbd-requirer",
            remote_app_data=(
                {
                    "auth_key": '"***"',
                    "auth_key_id": json.dumps(auth_key_secret.id),
                    "jwt_key": '"***"',
                    "jwt_key_id": json.dumps(jwt_key_secret.id),
                }
                if ready
                else {"auth_key": '"***"', "jwt_key": '"***"'}
            ),
        )

        state = provider_ctx.run(
            provider_ctx.on.relation_changed(slurmdbd_integration),
            testing.State(
                leader=leader,
                relations={slurmdbd_integration},
                secrets={auth_key_secret, jwt_key_secret},
            ),
        )

        if leader:
            if ready:
                # Assert that `SlurmctldReadyEvent` was emitted only once.
                occurred = defaultdict(lambda: 0)
                for event in provider_ctx.emitted_events:
                    occurred[type(event)] += 1

                assert occurred[SlurmctldReadyEvent] == 1

                # Assert that there are no deferred events.
                assert len(state.deferred) == 0

                # Assert that the unit is not waiting for controller data.
                assert state.unit_status != ops.WaitingStatus("Waiting for controller data")
            else:
                # Assert that the charm defers events if there's missing integration data.
                assert len(state.deferred) == 1
                assert state.unit_status == ops.WaitingStatus("Waiting for controller data")
        else:
            # Assert that `SlurmctldReadyEvent` is never emitted on non-leader units.
            assert not any(
                isinstance(event, SlurmctldReadyEvent) for event in provider_ctx.emitted_events
            )

            # Assert that the non-leader unit is not waiting for controller data.
            assert state.unit_status != ops.WaitingStatus("Waiting for controller data")

    def test_provider_on_slurmctld_disconnected_event(self, provider_ctx, leader) -> None:
        """Test that the `slurmdbd` provider properly captures when `slurmctld` is disconnected."""
        slurmdbd_integration_id = 1
        slurmdbd_integration = testing.Relation(
            endpoint=SLURMDBD_INTEGRATION_NAME,
            interface="slurmdbd",
            id=slurmdbd_integration_id,
            remote_app_name="slurmdbd-requirer",
        )

        provider_ctx.run(
            provider_ctx.on.relation_broken(slurmdbd_integration),
            testing.State(
                leader=leader,
                relations={slurmdbd_integration},
            ),
        )

        if leader:
            # Assert that `SlurmctldDisconnectedEvent` was emitted only once.
            occurred = defaultdict(lambda: 0)
            for event in provider_ctx.emitted_events:
                occurred[type(event)] += 1

            assert occurred[SlurmctldDisconnectedEvent] == 1
        else:
            # Assert that `SlurmctldDisconnectedEvent` is never emitted on non-leader units.
            assert not any(
                isinstance(event, SlurmctldDisconnectedEvent)
                for event in provider_ctx.emitted_events
            )

    # Test requires-side of the `slurmdbd` interface.

    def test_requirer_on_slurmdbd_connected_event(self, requirer_ctx, leader) -> None:
        """Test that the `slurmdbd` requirer sets controller data."""
        slurmdbd_integration_id = 1
        slurmdbd_integration = testing.Relation(
            endpoint=SLURMDBD_INTEGRATION_NAME,
            interface="slurmdbd",
            id=slurmdbd_integration_id,
            remote_app_name="slurmdbd-provider",
        )

        state = requirer_ctx.run(
            requirer_ctx.on.relation_created(slurmdbd_integration),
            testing.State(leader=leader, relations={slurmdbd_integration}),
        )

        if leader:
            integration = state.get_relation(slurmdbd_integration_id)

            # Assert `auth_key` is redacted in the integration data.
            assert integration.local_app_data["auth_key"] == '"***"'

            # Assert that `auth_key_id` is set to the `auth_key` secret URI.
            assert integration.local_app_data["auth_key_id"] != '""'

            # Assert `jwt_key` is redacted in the integration data.
            assert integration.local_app_data["jwt_key"] == '"***"'

            # Assert that `jwt_key_id` is set to the `jwt_key` secret URI.
            assert integration.local_app_data["jwt_key_id"] != '""'

            # Assert that `SlurmdbdConnectedEvent` was emitted only once.
            occurred = defaultdict(lambda: 0)
            for event in requirer_ctx.emitted_events:
                occurred[type(event)] += 1

            assert occurred[SlurmdbdConnectedEvent] == 1

            # Assert that there are no deferred events.
            assert len(state.deferred) == 0
        else:
            # Assert that `SlurmdbdConnectedEvent` is never emitted on non-leader units, nor do they
            # defer any events event if the `slurmdbd` provider application is not ready.
            assert not any(
                isinstance(event, SlurmdbdConnectedEvent) for event in requirer_ctx.emitted_events
            )
            assert len(state.deferred) == 0

    @pytest.mark.parametrize(
        "ready",
        (
            pytest.param(True, id="ready"),
            pytest.param(False, id="not ready"),
        ),
    )
    def test_requirer_on_slurmdbd_ready_event(self, requirer_ctx, leader, ready) -> None:
        """Test that the `slurmdbd` requirer waits for database data."""
        slurmdbd_integration_id = 1
        slurmdbd_integration = testing.Relation(
            endpoint=SLURMDBD_INTEGRATION_NAME,
            interface="slurmdbd",
            id=slurmdbd_integration_id,
            remote_app_name="slurmdbd-provider",
            remote_app_data=(
                {
                    "hostname": json.dumps(EXAMPLE_HOSTNAME),
                }
                if ready
                else {"nonce": "xyz123"}
            ),
        )

        state = requirer_ctx.run(
            requirer_ctx.on.relation_changed(slurmdbd_integration),
            testing.State(
                leader=leader,
                relations={slurmdbd_integration},
            ),
        )

        if leader:
            if ready:
                # Assert that `SlurmdbdReadyEvent` was emitted only once.
                occurred = defaultdict(lambda: 0)
                for event in requirer_ctx.emitted_events:
                    occurred[type(event)] += 1

                assert occurred[SlurmdbdReadyEvent] == 1

                # Assert that there are no deferred events.
                assert len(state.deferred) == 0

                # Assert that the leader unit is not waiting for database data.
                assert state.unit_status != ops.WaitingStatus("Waiting for database data")
            else:
                assert state.unit_status == ops.WaitingStatus("Waiting for database data")
                assert len(state.deferred) == 1
        else:
            # Assert that `SlurmdbdReadyEvent` is never emitted on non-leader units, nor do they
            # defer any events event if the `slurmdbd` provider application is not ready.
            assert not any(
                isinstance(event, SlurmdbdReadyEvent) for event in requirer_ctx.emitted_events
            )
            assert len(state.deferred) == 0

    def test_requirer_on_slurmdbd_disconnected_event(self, requirer_ctx, leader) -> None:
        """Test that the `slurmdbd` requirer properly captures when a database is disconnected."""
        slurmdbd_integration_id = 1
        slurmdbd_integration = testing.Relation(
            endpoint=SLURMDBD_INTEGRATION_NAME,
            interface="slurmdbd",
            id=slurmdbd_integration_id,
            remote_app_name="slurmdbd-provider",
        )

        requirer_ctx.run(
            requirer_ctx.on.relation_broken(slurmdbd_integration),
            testing.State(
                leader=leader,
                relations={slurmdbd_integration},
            ),
        )

        if leader:
            # Assert that `SlurmdbdDisconnectedEvent` was emitted only once.
            occurred = defaultdict(lambda: 0)
            for event in requirer_ctx.emitted_events:
                occurred[type(event)] += 1

            assert occurred[SlurmdbdDisconnectedEvent] == 1
        else:
            # Assert that `SlurmdbdDisconnectedEvent` is never emitted on non-leader units.
            assert not any(
                isinstance(event, SlurmdbdDisconnectedEvent)
                for event in requirer_ctx.emitted_events
            )
