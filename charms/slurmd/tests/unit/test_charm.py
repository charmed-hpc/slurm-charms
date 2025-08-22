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

"""Unit tests for the `slurmd` charmed operator."""

import json

import ops
import pytest
from constants import SLURMD_INTEGRATION_NAME
from ops import testing
from pytest_mock import MockerFixture
from slurm_ops import SlurmOpsError
from slurmutils import Node

EXAMPLE_AUTH_KEY = "xyz123=="
EXAMPLE_CONTROLLERS = ["juju-988225-0:6817", "juju-988225-1:6817"]
EXAMPLE_NHC_ARGS = "-X -v"


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSlurmdCharm:
    """Unit tests for the `slurmd` charmed operator."""

    @pytest.mark.parametrize(
        "mock_partition,expected",
        (
            pytest.param(None, ops.WaitingStatus("Waiting for `slurmd` to start"), id="success"),
            pytest.param(
                lambda _: (_ for _ in ()).throw(SlurmOpsError("failed to load config")),
                ops.BlockedStatus(
                    "Failed to update partition configuration. "
                    + "See `juju debug-log` for details"
                ),
                id="fail",
            ),
        ),
    )
    def test_on_slurmctld_connected(
        self, mock_charm, mocker: MockerFixture, mock_partition, leader, expected
    ) -> None:
        """Test the `_on_slurmd_connected` event handler."""
        integration_id = 1
        integration = testing.Relation(
            endpoint=SLURMD_INTEGRATION_NAME,
            interface="slurmd",
            id=integration_id,
            remote_app_name="slurmctld",
        )

        with mock_charm(
            mock_charm.on.relation_created(integration),
            testing.State(leader=leader, relations={integration}),
        ) as manager:
            slurmd = manager.charm.slurmd
            mocker.patch.object(slurmd, "is_installed", return_value=True)
            if mock_partition:
                mocker.patch("slurmutils.Partition.from_str", mock_partition)

            state = manager.run()

        if leader:
            assert state.unit_status == expected
        else:
            # Assert that non-leader units do not:
            #   1. handle `_on_slurmctld_connected`.
            #   2. set a status message.
            assert state.unit_status == ops.UnknownStatus()

    @pytest.mark.parametrize(
        "mock_restart,ready,expected",
        (
            pytest.param(
                lambda: None,
                True,
                ops.ActiveStatus(),
                id="ready-start success",
            ),
            pytest.param(
                lambda: (_ for _ in ()).throw(SlurmOpsError("restart failed")),
                True,
                ops.BlockedStatus(
                    "Failed to apply new `slurmd` configuration. See `juju debug-log` for details"
                ),
                id="ready-start fail",
            ),
            pytest.param(
                lambda: None,
                False,
                ops.WaitingStatus("Waiting for controller data"),
                id="not ready-start success",
            ),
            pytest.param(
                lambda: (_ for _ in ()).throw(SlurmOpsError("restart failed")),
                False,
                ops.WaitingStatus("Waiting for controller data"),
                id="not ready-start fail",
            ),
        ),
    )
    def test_on_slurmctld_ready(
        self, mock_charm, mocker: MockerFixture, mock_restart, ready, leader, expected
    ) -> None:
        """Test the `_on_slurmctld_ready` event handler."""
        auth_key_secret = testing.Secret(tracked_content={"key": EXAMPLE_AUTH_KEY})

        integration_id = 1
        integration = testing.Relation(
            endpoint=SLURMD_INTEGRATION_NAME,
            interface="slurmd",
            id=integration_id,
            remote_app_name="slurmctld",
            remote_app_data=(
                {
                    "auth_key": '"***"',
                    "auth_key_id": json.dumps(auth_key_secret.id),
                    "controllers": json.dumps(EXAMPLE_CONTROLLERS),
                    "nhc_args": json.dumps(EXAMPLE_NHC_ARGS),
                }
                if ready
                else {
                    "auth_key": '"***"',
                    "auth_key_id": json.dumps(auth_key_secret.id),
                    "controllers": json.dumps([]),
                    "nhc_args": json.dumps(EXAMPLE_NHC_ARGS),
                }
            ),
        )

        with mock_charm(
            mock_charm.on.relation_changed(integration),
            testing.State(
                leader=leader,
                relations={integration},
                secrets={auth_key_secret},
            ),
        ) as manager:
            slurmd = manager.charm.slurmd
            mocker.patch.object(slurmd, "is_installed", return_value=True)
            mocker.patch.object(slurmd.service, "is_active")
            mocker.patch.object(slurmd.service, "restart", mock_restart)
            mocker.patch("config.get_node_info", return_value=Node(cpus=8))
            mocker.patch("shutil.chown")  # User/group `slurm` doesn't exist on host.

            state = manager.run()

        assert state.unit_status == expected

    @pytest.mark.parametrize(
        "mock_stop,expected",
        (
            pytest.param(
                lambda: None,
                ops.BlockedStatus("Waiting for integrations: [`slurmctld`]"),
                id="stop success",
            ),
            pytest.param(
                lambda: (_ for _ in ()).throw(SlurmOpsError("install failed")),
                ops.BlockedStatus("Failed to stop `slurmd`. See `juju debug-log` for details"),
                id="stop fail",
            ),
        ),
    )
    def test_on_slurmctld_disconnected(
        self, mock_charm, mocker: MockerFixture, mock_stop, leader, expected
    ) -> None:
        """Test the `_on_slurmctld_disconnected` event handler."""
        auth_key_secret = testing.Secret(tracked_content={"key": EXAMPLE_AUTH_KEY})

        integration_id = 1
        integration = testing.Relation(
            endpoint=SLURMD_INTEGRATION_NAME,
            interface="sackd",
            id=integration_id,
            remote_app_name="slurmctld",
            remote_app_data={
                "auth_key": '"***"',
                "auth_key_id": json.dumps(auth_key_secret.id),
                "controllers": json.dumps(EXAMPLE_CONTROLLERS),
                "nhc_args": json.dumps(EXAMPLE_NHC_ARGS),
            },
        )

        with mock_charm(
            mock_charm.on.relation_broken(integration),
            testing.State(leader=leader, relations={integration}, secrets={auth_key_secret}),
        ) as manager:
            slurmd = manager.charm.slurmd
            mocker.patch.object(slurmd, "is_installed", return_value=True)
            mocker.patch.object(slurmd.service, "stop", mock_stop)

            state = manager.run()

        assert state.unit_status == expected
