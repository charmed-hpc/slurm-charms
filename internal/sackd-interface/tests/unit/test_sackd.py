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

"""Unit tests for the `sackd` integration interface implementation."""

import json
from collections import defaultdict

import ops
import pytest
from charmed_hpc_libs.ops.conditions import refresh, wait_unless
from charmed_slurm_sackd_interface import (
    AUTH_KEY_LABEL,
    SackdConnectedEvent,
    SackdProvider,
    SackdRequirer,
    SlurmctldDisconnectedEvent,
    SlurmctldReadyEvent,
    controller_ready,
)
from charmed_slurm_slurmctld_interface import ControllerData
from ops import testing

SACKD_INTEGRATION_NAME = "sackd"
EXAMPLE_AUTH_KEY = "xyz123=="
EXAMPLE_AUTH_KEY_ID = "12345678-90ab-cdef-1234-567890abcdef"
EXAMPLE_CONTROLLERS = ["127.0.0.1", "127.0.1.1"]


class MockSackdProviderCharm(ops.CharmBase):
    """Mock `sackd` provider charm."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self.slurmctld = SackdProvider(self, SACKD_INTEGRATION_NAME)

        framework.observe(
            self.slurmctld.on.slurmctld_ready,
            self._on_slurmctld_ready,
        )

    @refresh(hook=None)
    @wait_unless(controller_ready)
    def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
        data = self.slurmctld.get_controller_data(integration_id=event.relation.id)
        # Assume `remote_app_data` contains `auth_key` and `controllers` list.
        assert data.auth_key == EXAMPLE_AUTH_KEY
        assert data.controllers == EXAMPLE_CONTROLLERS

    def _on_slurmctld_disconnected(self, event: SlurmctldDisconnectedEvent) -> None: ...


class MockSackdRequirerCharm(ops.CharmBase):
    """Mock `sackd` requirer charm."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self.sackd = SackdRequirer(self, SACKD_INTEGRATION_NAME)

        framework.observe(
            self.sackd.on.sackd_connected,
            self._on_sackd_connected,
        )

    def _on_sackd_connected(self, event: SackdConnectedEvent) -> None:
        auth_key_secret = self.app.add_secret(
            {"key": EXAMPLE_AUTH_KEY, "keyid": EXAMPLE_AUTH_KEY_ID}, label=AUTH_KEY_LABEL
        )
        self.sackd.set_controller_data(
            ControllerData(
                auth_secret_id=auth_key_secret.get_info().id,
                controllers=EXAMPLE_CONTROLLERS,
            ),
            integration_id=event.relation.id,
        )


@pytest.fixture(scope="function")
def provider_ctx() -> testing.Context[MockSackdProviderCharm]:
    return testing.Context(
        MockSackdProviderCharm,
        meta={
            "name": "sackd-provider",
            "provides": {SACKD_INTEGRATION_NAME: {"interface": "sackd"}},
        },
    )


@pytest.fixture(scope="function")
def requirer_ctx() -> testing.Context[MockSackdRequirerCharm]:
    return testing.Context(
        MockSackdRequirerCharm,
        meta={
            "name": "sackd-requirer",
            "requires": {SACKD_INTEGRATION_NAME: {"interface": "sackd"}},
        },
    )


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSackdInterface:
    """Unit tests for the `sackd` integration interface implementation."""

    # Test provider-side of the `sackd` interface.

    @pytest.mark.parametrize(
        "ready",
        (
            pytest.param(True, id="ready"),
            pytest.param(False, id="not ready"),
        ),
    )
    def test_provider_on_slurmctld_ready_event(self, provider_ctx, leader, ready) -> None:
        """Test that the `sackd` provider waits for controller data."""
        auth_key_secret = testing.Secret(
            label=AUTH_KEY_LABEL,
            tracked_content={"key": EXAMPLE_AUTH_KEY, "keyid": EXAMPLE_AUTH_KEY_ID},
        )

        sackd_integration_id = 1
        sackd_integration = testing.Relation(
            endpoint=SACKD_INTEGRATION_NAME,
            interface="sackd",
            id=sackd_integration_id,
            remote_app_name="sackd-requirer",
            remote_app_data=(
                {
                    "auth_secret_id": json.dumps(auth_key_secret.id),
                    "controllers": json.dumps(EXAMPLE_CONTROLLERS),
                }
                if ready
                else {
                    "auth_secret_id": json.dumps(""),
                    "controllers": json.dumps([]),
                }
            ),
        )

        state = provider_ctx.run(
            provider_ctx.on.relation_changed(sackd_integration),
            testing.State(
                leader=leader,
                relations={sackd_integration},
                secrets={auth_key_secret},
            ),
        )

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

    # Test requires-side of the `sackd` interface.

    def test_requirer_on_sackd_connected_event(self, requirer_ctx, leader) -> None:
        """Test that `slurmctld` sets required integration data for `sackd` to function."""
        sackd_integration_id = 1
        sackd_integration = testing.Relation(
            endpoint=SACKD_INTEGRATION_NAME,
            interface="sackd",
            id=sackd_integration_id,
            remote_app_name="sackd-provider",
        )

        state = requirer_ctx.run(
            requirer_ctx.on.relation_created(sackd_integration),
            testing.State(
                leader=leader,
                relations={sackd_integration},
            ),
        )

        integration = state.get_relation(sackd_integration_id)
        if leader:
            # Verify that the leader unit has set the required data for `sackd`.
            assert "auth_secret_id" in integration.local_app_data
            assert integration.local_app_data["auth_secret_id"] != '""'

            assert "controllers" in integration.local_app_data
            assert integration.local_app_data["controllers"] == json.dumps(EXAMPLE_CONTROLLERS)
        else:
            # Verify that non-leader units have not set anything in `local_app_data`.
            assert integration.local_app_data == {}
