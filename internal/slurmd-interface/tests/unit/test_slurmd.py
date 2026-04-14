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

"""Unit tests for the `slurmd` integration interface implementation."""

import json
from collections import defaultdict

import ops
import pytest
from charmed_hpc_libs.ops.conditions import refresh, wait_unless
from charmed_slurm_slurmctld_interface import ControllerData
from charmed_slurm_slurmd_interface import (
    AUTH_KEY_LABEL,
    ComputeData,
    SlurmctldConnectedEvent,
    SlurmctldReadyEvent,
    SlurmdDisconnectedEvent,
    SlurmdProvider,
    SlurmdReadyEvent,
    SlurmdRequirer,
    controller_ready,
    partition_ready,
)
from ops import testing
from slurmutils import Partition

SLURMD_INTEGRATION_NAME = "slurmd"
EXAMPLE_AUTH_KEY = "xyz123=="
EXAMPLE_AUTH_KEY_ID = "12345678-90ab-cdef-1234-567890abcdef"
EXAMPLE_CONTROLLERS = ["127.0.0.1", "127.0.1.1"]
EXAMPLE_PARTITION_CONFIG = Partition(partitionname="polaris")


class MockSlurmdProviderCharm(ops.CharmBase):
    """Mock `slurmd` provider charm."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmctld = SlurmdProvider(self, SLURMD_INTEGRATION_NAME)

        framework.observe(
            self.on.config_changed,
            self._on_config_changed,
        )
        framework.observe(
            self.slurmctld.on.slurmctld_connected,
            self._on_slurmctld_connected,
        )
        framework.observe(
            self.slurmctld.on.slurmctld_ready,
            self._on_slurmctld_ready,
        )

    def _on_config_changed(self, _: ops.ConfigChangedEvent) -> None:
        custom = self.config.get("partition-config", "")
        if custom and self.slurmctld.is_joined() and self.unit.is_leader():
            partition = Partition.from_str(custom)
            partition.partition_name = "polaris"
            self.slurmctld.set_compute_data(ComputeData(partition=partition))

    def _on_slurmctld_connected(self, event: SlurmctldConnectedEvent) -> None:
        self.slurmctld.set_compute_data(
            ComputeData(partition=EXAMPLE_PARTITION_CONFIG),
            integration_id=event.relation.id,
        )

    @refresh(hook=None)
    @wait_unless(controller_ready)
    def _on_slurmctld_ready(self, event: SlurmctldReadyEvent) -> None:
        data = self.slurmctld.get_controller_data(integration_id=event.relation.id)
        # Assume `remote_app_data` contains and `auth_key` and `controllers` list.
        assert data.auth_key == EXAMPLE_AUTH_KEY
        assert data.controllers == EXAMPLE_CONTROLLERS


class MockSlurmdRequirerCharm(ops.CharmBase):
    """Mock `slurmd` requirer charm."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self.slurmd = SlurmdRequirer(self, SLURMD_INTEGRATION_NAME)

        framework.observe(
            self.slurmd.on.slurmd_ready,
            self._on_slurmd_ready,
        )
        framework.observe(
            self.slurmd.on.slurmd_disconnected,
            self._on_slurmd_disconnected,
        )

    @refresh(hook=None)
    @wait_unless(partition_ready)
    def _on_slurmd_ready(self, event: SlurmdReadyEvent) -> None:
        data = self.slurmd.get_compute_data(integration_id=event.relation.id)
        # Assume `remote_app_data` contains partition configuration data.
        assert data.partition.dict() == EXAMPLE_PARTITION_CONFIG.dict()

        auth_key_secret = self.app.add_secret(
            {"key": EXAMPLE_AUTH_KEY, "keyid": EXAMPLE_AUTH_KEY_ID}, label=AUTH_KEY_LABEL
        )

        self.slurmd.set_controller_data(
            ControllerData(
                auth_secret_id=auth_key_secret.get_info().id,
                controllers=EXAMPLE_CONTROLLERS,
            ),
            integration_id=event.relation.id,
        )

    def _on_slurmd_disconnected(self, event: SlurmdDisconnectedEvent) -> None: ...


@pytest.fixture(scope="function")
def provider_ctx() -> testing.Context[MockSlurmdProviderCharm]:
    return testing.Context(
        MockSlurmdProviderCharm,
        meta={
            "name": "slurmd-provider",
            "provides": {SLURMD_INTEGRATION_NAME: {"interface": "slurmd"}},
        },
        config={"options": {"partition-config": {"type": "string", "default": ""}}},
    )


@pytest.fixture(scope="function")
def requirer_ctx() -> testing.Context[MockSlurmdRequirerCharm]:
    return testing.Context(
        MockSlurmdRequirerCharm,
        meta={
            "name": "slurmd-requirer",
            "requires": {SLURMD_INTEGRATION_NAME: {"interface": "slurmd"}},
        },
    )


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSlurmdInterface:
    """Unit tests for the `slurmd` integration interface implementation."""

    # Test provider-side of `slurmd` interface.

    @pytest.mark.parametrize(
        "joined", (pytest.param(True, id="joined"), pytest.param(False, id="not joined"))
    )
    def test_provider_on_config_changed_event(self, provider_ctx, joined, leader) -> None:
        """Test that the `slurmd` provider correctly manages custom partition configuration."""
        slurmd_integration_id = 22
        slurmd_integration = testing.Relation(
            endpoint=SLURMD_INTEGRATION_NAME,
            interface="slurmd",
            id=slurmd_integration_id,
            remote_app_name="slurmd-requirer",
        )

        state = provider_ctx.run(
            provider_ctx.on.config_changed(),
            testing.State(
                leader=leader,
                config={"partition-config": "maxcpuspernode=16 maxmempercpu=8000"},
                relations={slurmd_integration} if joined else {},
            ),
        )

        if leader and joined:
            integration = state.get_relation(slurmd_integration_id)

            assert "partition" in integration.local_app_data
            partition = Partition.from_json(integration.local_app_data["partition"])
            assert partition.partition_name == "polaris"
            assert partition.max_cpus_per_node == 16
            assert partition.max_mem_per_cpu == 8000
        elif not leader and joined:
            integration = state.get_relation(slurmd_integration_id)

            assert integration.local_app_data == {}
        else:
            with pytest.raises(KeyError):
                state.get_relation(slurmd_integration_id)

    def test_provider_on_slurmctld_connected_event(self, provider_ctx, leader) -> None:
        """Test that the `slurmd` provider correctly sets partition configuration data."""
        slurmd_integration_id = 22
        slurmd_integration = testing.Relation(
            endpoint=SLURMD_INTEGRATION_NAME,
            interface="slurmd",
            id=slurmd_integration_id,
            remote_app_name="slurmd-requirer",
        )

        state = provider_ctx.run(
            provider_ctx.on.relation_created(slurmd_integration),
            testing.State(
                leader=leader,
                relations={slurmd_integration},
            ),
        )

        integration = state.get_relation(slurmd_integration_id)
        if leader:
            # Verify that the leader unit has set partition data in `local_app_data`.
            assert "partition" in integration.local_app_data
            partition = Partition.from_json(integration.local_app_data["partition"])
            assert partition.dict() == EXAMPLE_PARTITION_CONFIG.dict()
        else:
            # Verify that non-leader units have not set anything in `local_app_data`.
            assert integration.local_app_data == {}

    @pytest.mark.parametrize(
        "ready",
        (
            pytest.param(True, id="ready"),
            pytest.param(False, id="not ready"),
        ),
    )
    def test_provider_on_slurmctld_ready_event(self, provider_ctx, ready, leader) -> None:
        """Test that the `slurmd` provider waits for controller data."""
        auth_key_secret = testing.Secret(tracked_content={"key": EXAMPLE_AUTH_KEY})

        slurmd_integration_id = 22
        slurmd_integration = testing.Relation(
            endpoint=SLURMD_INTEGRATION_NAME,
            interface="slurmd",
            id=slurmd_integration_id,
            remote_app_name="slurmd-requirer",
            remote_app_data=(
                {
                    "auth_secret_id": json.dumps(auth_key_secret.id),
                    "controllers": json.dumps(EXAMPLE_CONTROLLERS),
                }
                if ready
                else {
                    "auth_secret_id": json.dumps(auth_key_secret.id),
                    "controllers": json.dumps([]),
                }
            ),
        )

        state = provider_ctx.run(
            provider_ctx.on.relation_changed(slurmd_integration),
            testing.State(
                leader=leader,
                relations={slurmd_integration},
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

    # Test requires-side of `slurmd` interface.

    @pytest.mark.parametrize(
        "ready",
        (
            pytest.param(True, id="ready"),
            pytest.param(False, id="not ready"),
        ),
    )
    def test_requirer_on_slurmd_ready_event(self, requirer_ctx, ready, leader) -> None:
        """Test that the `slurmd` requirer waits for partition data."""
        slurmd_integration_id = 22
        slurmd_integration = testing.Relation(
            endpoint=SLURMD_INTEGRATION_NAME,
            interface="slurmd",
            id=slurmd_integration_id,
            remote_app_name="slurmd-provider",
            remote_app_data=(
                {
                    "partition": EXAMPLE_PARTITION_CONFIG.json(),
                }
                if ready
                else {"nonce": "xyz123"}
            ),
        )

        state = requirer_ctx.run(
            requirer_ctx.on.relation_changed(slurmd_integration),
            testing.State(leader=leader, relations={slurmd_integration}),
        )

        if leader:
            if ready:
                integration = state.get_relation(slurmd_integration_id)

                # Assert that `auth_key_id` is set to the `auth_key` secret URI.
                assert integration.local_app_data["auth_secret_id"] != '""'

                # Assert that `SlurmdReadyEvent` was emitted only once.
                occurred = defaultdict(lambda: 0)
                for event in requirer_ctx.emitted_events:
                    occurred[type(event)] += 1

                assert occurred[SlurmdReadyEvent] == 1

                # Assert that there are no deferred events.
                assert len(state.deferred) == 0

                # Assert that the leader unit is not waiting for partition data.
                assert state.unit_status != ops.WaitingStatus("Waiting for partition data")
            else:
                assert state.unit_status == ops.WaitingStatus("Waiting for partition data")
                assert len(state.deferred) == 1
        else:
            # Assert that `SlurmdReadyEvent` is never emitted on non-leader units, nor do they
            # defer any events event if the `slurmd` provider application is not ready.
            assert not any(
                isinstance(event, SlurmdReadyEvent) for event in requirer_ctx.emitted_events
            )
            assert len(state.deferred) == 0

    def test_requirer_on_slurmd_disconnected_event(self, requirer_ctx, leader) -> None:
        """Test that the `slurmd` requirer properly captures when a partition is disconnected."""
        slurmd_integration_id = 22
        slurmd_integration = testing.Relation(
            endpoint=SLURMD_INTEGRATION_NAME,
            interface="slurmd",
            id=slurmd_integration_id,
            remote_app_name="slurmd-provider",
        )

        requirer_ctx.run(
            requirer_ctx.on.relation_broken(slurmd_integration),
            testing.State(
                leader=leader,
                relations={slurmd_integration},
            ),
        )

        if leader:
            # Assert that `SlurmdDisconnectedEvent` was emitted only once.
            occurred = defaultdict(lambda: 0)
            for event in requirer_ctx.emitted_events:
                occurred[type(event)] += 1

            assert occurred[SlurmdDisconnectedEvent] == 1
        else:
            # Assert that `SlurmdDisconnectedEvent` is never emitted on non-leader units.
            assert not any(
                isinstance(event, SlurmdDisconnectedEvent) for event in requirer_ctx.emitted_events
            )
