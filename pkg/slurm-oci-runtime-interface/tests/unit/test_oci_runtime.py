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

"""Unit tests for the `slurm_oci_runtime` integration interface implementation."""

from collections import defaultdict

import ops
import pytest
from charmed_slurm_oci_runtime_interface import (
    OCIRuntimeData,
    OCIRuntimeDisconnectedEvent,
    OCIRuntimeProvider,
    OCIRuntimeReadyEvent,
    OCIRuntimeRequirer,
)
from charmed_slurm_slurmctld_interface import SlurmctldConnectedEvent
from ops import testing
from slurmutils import OCIConfig

OCI_RUNTIME_INTEGRATION_NAME = "oci-runtime"
EXAMPLE_OCI_CONFIG = OCIConfig(
    ignorefileconfigjson=False,
    envexclude="^(SLURM_CONF|SLURM_CONF_SERVER)=",
    runtimeenvexclude="^(SLURM_CONF|SLURM_CONF_SERVER)=",
    runtimerun="apptainer exec --userns %r %@",
    runtimekill="kill -s SIGTERM %p",
    runtimedelete="kill -s SIGKILL %p",
)


class MockOCIRunTimeProviderCharm(ops.CharmBase):
    """Mock OCI runtime provider charm."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self._oci_runtime = OCIRuntimeProvider(self, OCI_RUNTIME_INTEGRATION_NAME)

        framework.observe(self._oci_runtime.on.slurmctld_connected, self._on_slurmctld_connected)

    def _on_slurmctld_connected(self, event: SlurmctldConnectedEvent) -> None:
        self._oci_runtime.set_oci_runtime_data(
            OCIRuntimeData(ociconfig=EXAMPLE_OCI_CONFIG),
            integration_id=event.relation.id,
        )


class MockOCIRunTimeRequirerCharm(ops.CharmBase):
    """Mock OCI runtime requirer charm."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)

        self._oci_runtime = OCIRuntimeRequirer(self, OCI_RUNTIME_INTEGRATION_NAME)

        framework.observe(
            self._oci_runtime.on.oci_runtime_ready,
            self._on_oci_runtime_ready,
        )
        framework.observe(
            self._oci_runtime.on.oci_runtime_disconnected,
            self._on_oci_runtime_disconnected,
        )

    def _on_oci_runtime_ready(self, event: OCIRuntimeReadyEvent) -> None:
        config = self._oci_runtime.get_oci_runtime_data(event.relation.id)
        # Assume `remote_app_data` contains `oci.conf` configuration data.
        assert config.ociconfig.dict() == EXAMPLE_OCI_CONFIG.dict()

    def _on_oci_runtime_disconnected(self, event: OCIRuntimeDisconnectedEvent) -> None: ...


@pytest.fixture(scope="function")
def provider_ctx() -> testing.Context[MockOCIRunTimeProviderCharm]:
    return testing.Context(
        MockOCIRunTimeProviderCharm,
        meta={
            "name": "oci-runtime-provider",
            "provides": {OCI_RUNTIME_INTEGRATION_NAME: {"interface": "slurm_oci_runtime"}},
        },
    )


@pytest.fixture(scope="function")
def requirer_ctx() -> testing.Context[MockOCIRunTimeRequirerCharm]:
    return testing.Context(
        MockOCIRunTimeRequirerCharm,
        meta={
            "name": "oci-runtime-requirer",
            "requires": {OCI_RUNTIME_INTEGRATION_NAME: {"interface": "slurm_oci_runtime"}},
        },
    )


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSlurmOCIRunTimeInterface:
    """Unit tests for the `slurm-oci-runtime` integration interface implementation."""

    # Test provider-side of the `slurm-oci-runtime` interface.

    def test_provider_slurmctld_connected_event(self, provider_ctx, leader) -> None:
        """Test that an OCI runtime provider correctly sets `oci.conf` data in application data."""
        oci_runtime_integration_id = 1
        oci_runtime_integration = testing.Relation(
            endpoint=OCI_RUNTIME_INTEGRATION_NAME,
            interface="slurm_oci_runtime",
            id=oci_runtime_integration_id,
            remote_app_name="oci-runtime-requirer",
        )

        state = provider_ctx.run(
            provider_ctx.on.relation_created(oci_runtime_integration),
            testing.State(
                leader=leader,
                relations={oci_runtime_integration},
            ),
        )

        integration = state.get_relation(oci_runtime_integration_id)
        if leader:
            # Verify that the leader unit has set `oci.conf` data in `local_app_data`.
            assert "ociconfig" in integration.local_app_data
            config = OCIConfig.from_json(integration.local_app_data["ociconfig"])
            assert config.dict() == EXAMPLE_OCI_CONFIG.dict()
        else:
            # Verify that non-leader units have not set anything in `local_app_data`.
            assert integration.local_app_data == {}

    # Test requirer-side of the `slurm-oci-runtime` interface.

    @pytest.mark.parametrize(
        "ready",
        (
            pytest.param(True, id="ready"),
            pytest.param(False, id="not ready"),
        ),
    )
    def test_requirer_oci_runtime_ready_event(self, requirer_ctx, leader, ready) -> None:
        """Test that an OCI runtime requirer can consume `oci.conf` data from a runtime provider."""
        oci_runtime_integration_id = 1
        oci_runtime_integration = testing.Relation(
            endpoint=OCI_RUNTIME_INTEGRATION_NAME,
            interface="slurm_oci_runtime",
            id=oci_runtime_integration_id,
            remote_app_name="oci-runtime-provider",
            remote_app_data={"ociconfig": EXAMPLE_OCI_CONFIG.json()} if ready else {},
        )

        requirer_ctx.run(
            requirer_ctx.on.relation_changed(oci_runtime_integration),
            testing.State(leader=leader, relations={oci_runtime_integration}),
        )

        if leader and ready:
            # Assert that `OCIRuntimeReadyEvent` was emitted only once.
            occurred = defaultdict(lambda: 0)
            for event in requirer_ctx.emitted_events:
                occurred[type(event)] += 1

            assert occurred[OCIRuntimeReadyEvent] == 1
        else:
            # Assert that `OCIRuntimeReadyEvent` is never emitted on non-leader units or on the
            # leader unit if `remote_app_data` is empty - e.g. blank `RelationChangedEvent` emitted
            # after `slurmctld` and `oci-runtime-provider` are integrated together.
            assert not any(
                isinstance(event, OCIRuntimeReadyEvent) for event in requirer_ctx.emitted_events
            )

    def test_requirer_oci_runtime_disconnected_event(self, requirer_ctx, leader) -> None:
        """Test that an OCI requirer properly captures when the runtime provider is disconnected."""
        oci_runtime_integration_id = 1
        oci_runtime_integration = testing.Relation(
            endpoint=OCI_RUNTIME_INTEGRATION_NAME,
            interface="slurm_oci_runtime",
            id=oci_runtime_integration_id,
            remote_app_name="oci-runtime-provider",
        )

        requirer_ctx.run(
            requirer_ctx.on.relation_broken(oci_runtime_integration),
            testing.State(leader=leader, relations={oci_runtime_integration}),
        )

        if leader:
            # Assert that `OCIRuntimeDisconnectedEvent` was emitted only once.
            occurred = defaultdict(lambda: 0)
            for event in requirer_ctx.emitted_events:
                occurred[type(event)] += 1

            assert occurred[OCIRuntimeDisconnectedEvent] == 1
        else:
            # Assert that `OCIRuntimeDisconnectedEvent` is never emitted on non-leader units.
            assert not any(
                isinstance(event, OCIRuntimeDisconnectedEvent)
                for event in requirer_ctx.emitted_events
            )
