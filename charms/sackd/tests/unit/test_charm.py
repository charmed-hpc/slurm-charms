#!/usr/bin/env python3
# Copyright 2023-2024 Canonical Ltd.
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

"""Unit tests for the `sackd` charmed operator."""

import json

import ops
import pytest
from constants import SACKD_INTEGRATION_NAME
from ops import testing
from pytest_mock import MockerFixture
from slurm_ops import SlurmOpsError

EXAMPLE_AUTH_KEY = "xyz123=="
EXAMPLE_CONTROLLERS = ["juju-988225-0:6817", "juju-988225-1:6817"]


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSackdCharm:
    """Unit tests for the `sackd` charmed operator."""

    @pytest.mark.parametrize(
        "mock_install,expected",
        (
            pytest.param(
                lambda: None,
                ops.BlockedStatus("Waiting for integrations: [`slurmctld`]"),
                id="success",
            ),
            pytest.param(
                lambda: (_ for _ in ()).throw(SlurmOpsError("install failed")),
                ops.BlockedStatus("Failed to install `sackd`. See `juju debug-log` for details"),
                id="fail",
            ),
        ),
    )
    def test_install(
        self,
        mock_charm,
        mocker: MockerFixture,
        mock_install,
        leader,
        expected,
    ) -> None:
        """Test the `_on_install` event handler."""
        with mock_charm(mock_charm.on.install(), testing.State(leader=leader)) as manager:
            sackd = manager.charm.sackd
            mocker.patch.object(sackd, "install", mock_install)
            mocker.patch.object(sackd, "is_installed")
            mocker.patch.object(sackd, "version", return_value="24.05.2-1")

            state = manager.run()

        assert state.unit_status == expected

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
                ops.BlockedStatus("Failed to start `sackd`. See `juju debug-log` for details"),
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
            endpoint=SACKD_INTEGRATION_NAME,
            interface="sackd",
            id=integration_id,
            remote_app_name="slurmctld",
            remote_app_data=(
                {
                    "auth_key": '"***"',
                    "auth_key_id": json.dumps(auth_key_secret.id),
                    "controllers": json.dumps(EXAMPLE_CONTROLLERS),
                }
                if ready
                else {"controllers": json.dumps(EXAMPLE_CONTROLLERS)}
            ),
        )

        with mock_charm(
            mock_charm.on.relation_changed(integration),
            testing.State(leader=leader, relations={integration}, secrets={auth_key_secret}),
        ) as manager:
            sackd = manager.charm.sackd
            mocker.patch.object(sackd, "is_installed", return_value=True)
            mocker.patch.object(sackd.service, "is_active")
            mocker.patch.object(sackd.service, "restart", mock_restart)
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
                ops.BlockedStatus("Failed to stop `sackd`. See `juju debug-log` for details"),
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
            endpoint=SACKD_INTEGRATION_NAME,
            interface="sackd",
            id=integration_id,
            remote_app_name="slurmctld",
            remote_app_data={
                "auth_key": '"***"',
                "auth_key_id": json.dumps(auth_key_secret.id),
                "controllers": json.dumps(EXAMPLE_CONTROLLERS),
            },
        )

        with mock_charm(
            mock_charm.on.relation_broken(integration),
            testing.State(leader=leader, relations={integration}, secrets={auth_key_secret}),
        ) as manager:
            sackd = manager.charm.sackd
            mocker.patch.object(sackd, "is_installed", return_value=True)
            mocker.patch.object(sackd.service, "stop", mock_stop)

            state = manager.run()

        assert state.unit_status == expected
