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

"""Unit tests for the `slurmctld` charm."""

import pytest
from constants import CLUSTER_NAME_PREFIX, PEER_INTEGRATION_NAME
from ops import testing
from pytest_mock import MockerFixture


@pytest.mark.parametrize(
    "cluster_name",
    (
        pytest.param("polaris", id="cluster name configured"),
        pytest.param("", id="no cluster name configured"),
    ),
)
@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
def test_on_slurmctld_peer_connected(
    mocker: MockerFixture, mock_charm, leader, cluster_name
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
            assert integration.local_app_data["cluster_name"] == f'"{CLUSTER_NAME_PREFIX}-{slug}"'
    else:
        assert "cluster_name" not in integration.local_app_data
