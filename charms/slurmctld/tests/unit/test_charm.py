#!/usr/bin/env python3
# Copyright 2023-2025 Canonical Ltd.
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

"""Unit tests for the `slurmctld` charmed operator."""

import pytest
from constants import CLUSTER_NAME_PREFIX, OCI_RUNTIME_INTEGRATION_NAME, PEER_INTEGRATION_NAME
from hpc_libs.interfaces import OCIRuntimeDisconnectedEvent, OCIRuntimeReadyEvent
from ops import testing
from pytest_mock import MockerFixture
from slurm_ops import SlurmOpsError
from slurmutils import OCIConfig

EXAMPLE_OCI_CONFIG = OCIConfig(
    ignorefileconfigjson=False,
    envexclude="^(SLURM_CONF|SLURM_CONF_SERVER)=",
    runtimeenvexclude="^(SLURM_CONF|SLURM_CONF_SERVER)=",
    runtimerun="apptainer exec --userns %r %@",
    runtimekill="kill -s SIGTERM %p",
    runtimedelete="kill -s SIGKILL %p",
)


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSlurmctldCharm:
    """Unit tests for the `slurmctld` charmed operator."""

    @pytest.mark.parametrize(
        "cluster_name",
        (
            pytest.param("polaris", id="cluster name configured"),
            pytest.param("", id="no cluster name configured"),
        ),
    )
    def test_on_slurmctld_peer_connected(
        self, mocker: MockerFixture, mock_charm, leader, cluster_name
    ) -> None:
        """Test the `_on_slurmctld_peer_connected` event handler."""
        # Patch `secrets.token_urlsafe(...)` to have predictable output.
        slug = "xyz1"
        mocker.patch("secrets.token_urlsafe", return_value=slug)

        peer_integration_id = 1
        peer_integration = testing.PeerRelation(
            endpoint=PEER_INTEGRATION_NAME,
            interface="slurmctld-peer",
            id=peer_integration_id,
        )

        state = mock_charm.run(
            mock_charm.on.relation_created(peer_integration),
            testing.State(
                leader=leader, relations={peer_integration}, config={"cluster-name": cluster_name}
            ),
        )

        integration = state.get_relation(peer_integration_id)
        if leader:
            assert "cluster_name" in integration.local_app_data
            if cluster_name:
                assert integration.local_app_data["cluster_name"] == '"polaris"'
            else:
                assert (
                    integration.local_app_data["cluster_name"] == f'"{CLUSTER_NAME_PREFIX}-{slug}"'
                )
        else:
            assert "cluster_name" not in integration.local_app_data

    @pytest.mark.parametrize(
        "ready",
        (
            pytest.param(True, id="ready"),
            pytest.param(False, id="not ready"),
        ),
    )
    def test_on_oci_runtime_ready(self, mock_charm, mocker: MockerFixture, ready, leader) -> None:
        """Test the `_on_oci_runtime_ready` event handler."""
        integration_id = 1
        integration = testing.Relation(
            endpoint=OCI_RUNTIME_INTEGRATION_NAME,
            interface="slurm-oci-runtime",
            id=integration_id,
            remote_app_name="apptainer",
            remote_app_data={"ociconfig": EXAMPLE_OCI_CONFIG.json()} if ready else {},
        )

        with mock_charm(
            mock_charm.on.relation_changed(integration),
            testing.State(leader=leader, relations={integration}),
        ) as manager:
            slurmctld = manager.charm.slurmctld
            mocker.patch.object(slurmctld, "is_installed", return_value=True)

            manager.run()

        if ready and leader:
            assert slurmctld.oci.path.exists()
            assert slurmctld.oci.load().dict() == EXAMPLE_OCI_CONFIG.dict()
        else:
            assert not slurmctld.oci.path.exists()
            # Assert that `OCIRuntimeReadyEvent` is never emitted on non-leader units or
            # on the leader unit if `remote_app_data` is empty.
            assert not any(
                isinstance(event, OCIRuntimeReadyEvent) for event in mock_charm.emitted_events
            )

    def test_on_oci_runtime_disconnected(self, mock_charm, mocker: MockerFixture, leader) -> None:
        """Test the `_on_oci_runtime_disconnected` event handler."""
        integration_id = 1
        integration = testing.Relation(
            endpoint=OCI_RUNTIME_INTEGRATION_NAME,
            interface="slurm-oci-runtime",
            id=integration_id,
            remote_app_name="apptainer",
        )

        with mock_charm(
            mock_charm.on.relation_broken(integration),
            testing.State(leader=leader, relations={integration}),
        ) as manager:
            slurmctld = manager.charm.slurmctld
            mocker.patch.object(slurmctld, "is_installed", return_value=True)

            manager.run()

        if leader:
            assert not slurmctld.oci.path.exists()
        else:
            # Assert that `OCIRuntimeDisconnectedEvent` is only handled by the `slurmctld` leader.
            assert not any(
                isinstance(event, OCIRuntimeDisconnectedEvent)
                for event in mock_charm.emitted_events
            )

    @pytest.mark.parametrize(
        "params,expected",
        (
            pytest.param(
                {"nodes": "slurmd-[0-19]", "state": "idle"},
                ("update", "nodename=slurmd-[0-19]", "state=idle"),
                id="idle",
            ),
            pytest.param(
                {"nodes": "slurmd-[20-24]", "state": "draining"},
                ("update", "nodename=slurmd-[20-24]", "state=draining", "reason='n/a'"),
                id="draining",
            ),
            pytest.param(
                {"nodes": "slurmd-[25-29]", "state": "down", "reason": "maintenance"},
                ("update", "nodename=slurmd-[25-29]", "state=down", "reason='maintenance'"),
                id="down",
            ),
        ),
    )
    def test_on_set_node_state_action(
        self, mock_charm, mock_scontrol, succeed, params, expected, leader
    ) -> None:
        """Test the `_on_set_node_state_action` action event handler."""
        if succeed:
            mock_charm.run(mock_charm.on.action("set-node-state", params=params), testing.State())
            mock_scontrol.assert_called_with(*expected)
        else:
            mock_scontrol.side_effect = [SlurmOpsError("scontrol failed")]
            with pytest.raises(testing.ActionFailed) as exec_info:
                mock_charm.run(
                    mock_charm.on.action("set-node-state", params=params), testing.State()
                )

            assert exec_info.value.message == (
                f"Failed to set state of node(s) {params['nodes']} to state '{params['state']}'. "
                f"reason:\nscontrol failed"
            )
