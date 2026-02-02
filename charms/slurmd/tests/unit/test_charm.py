#!/usr/bin/env python3
# Copyright 2023-2026 Canonical Ltd.
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
from constants import SLURMD_INTEGRATION_NAME, SLURMD_PORT
from hpc_libs.errors import SystemdError
from ops import testing
from pytest_mock import MockerFixture
from slurm_ops import SlurmOpsError
from slurmutils import Node

EXAMPLE_AUTH_KEY = "xyz123=="
EXAMPLE_CONTROLLERS = ["juju-988225-0:6817", "juju-988225-1:6817"]


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
        "mock_install,install_success",
        (
            pytest.param(None, True, id="install success"),
            pytest.param(SlurmOpsError("failed to install slurmd"), False, id="install fail"),
        ),
    )
    @pytest.mark.parametrize(
        "mock_gpu_autoinstall_success",
        (pytest.param(True, id="gpu detected"), pytest.param(False, id="gpu not detected")),
    )
    def test_on_install(
        self,
        mock_charm,
        mocker: MockerFixture,
        mock_install,
        install_success,
        mock_gpu_autoinstall_success,
        leader,
    ) -> None:
        """Test the `_on_install` event handler."""
        with mock_charm(mock_charm.on.install(), testing.State(leader=leader)) as manager:
            slurmd = manager.charm.slurmd

            # Patch `slurmd` manager.
            mocker.patch.object(slurmd, "install", side_effect=mock_install)
            mocker.patch.object(slurmd, "is_installed", lambda: install_success)
            mocker.patch.object(slurmd, "version", return_value="25.11")
            mocker.patch.object(slurmd.service, "stop")
            mocker.patch.object(slurmd.service, "disable")

            # Patch `rdma` module.
            mocker.patch("rdma.install")

            # Patch `gpu` module.
            mocker.patch("gpu.autoinstall", lambda: mock_gpu_autoinstall_success)

            state = manager.run()

        if install_success:
            assert slurmd.name == manager.charm.unit.name.replace("/", "-")
            assert slurmd.dynamic is True
            assert state.workload_version == "25.11"
            assert state.opened_ports == frozenset(
                {testing.TCPPort(port=SLURMD_PORT, protocol="tcp")}
            )

            if mock_gpu_autoinstall_success:
                assert (
                    ops.MaintenanceStatus("Successfully installed GPU drivers")
                    in mock_charm.unit_status_history
                )
            else:
                assert (
                    ops.MaintenanceStatus("No GPUs found. Continuing")
                    in mock_charm.unit_status_history
                )

            assert state.unit_status == ops.BlockedStatus(
                "Waiting for integrations: [`slurmctld`]"
            )
        else:
            assert len(state.deferred) > 0
            assert state.unit_status == ops.BlockedStatus(
                "`slurmd` is not installed. See `juju debug-log` for details"
            )

    @pytest.mark.parametrize(
        "mock_partition,expected",
        (
            pytest.param(None, ops.WaitingStatus("Waiting for `slurmd` to start"), id="success"),
            pytest.param(
                SlurmOpsError("failed to load config"),
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
                mocker.patch("slurmutils.Partition.from_str", side_effect=mock_partition)

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
                None,
                True,
                ops.ActiveStatus(),
                id="ready-start success",
            ),
            pytest.param(
                SystemdError("restart failed"),
                True,
                ops.BlockedStatus(
                    "Failed to apply new `slurmd` configuration. See `juju debug-log` for details"
                ),
                id="ready-start fail",
            ),
            pytest.param(
                None,
                False,
                ops.WaitingStatus("Waiting for controller data"),
                id="not ready-start success",
            ),
            pytest.param(
                SystemdError("restart failed"),
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
                }
                if ready
                else {
                    "auth_key": '"***"',
                    "auth_key_id": json.dumps(auth_key_secret.id),
                    "controllers": json.dumps([]),
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
            mocker.patch.object(slurmd.service, "restart", side_effect=mock_restart)
            mocker.patch.object(slurmd, "is_installed", return_value=True)
            mocker.patch.object(slurmd.service, "is_active")
            mocker.patch("config.get_node_info", return_value=Node(cpus=8))
            mocker.patch("shutil.chown")  # User/group `slurm` doesn't exist on host.

            state = manager.run()

        assert state.unit_status == expected

    @pytest.mark.parametrize(
        "mock_stop,expected",
        (
            pytest.param(
                None,
                ops.BlockedStatus("Waiting for integrations: [`slurmctld`]"),
                id="stop success",
            ),
            pytest.param(
                SystemdError("stop failed"),
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
            },
        )

        with mock_charm(
            mock_charm.on.relation_broken(integration),
            testing.State(leader=leader, relations={integration}, secrets={auth_key_secret}),
        ) as manager:
            slurmd = manager.charm.slurmd
            mocker.patch.object(slurmd.service, "stop", side_effect=mock_stop)
            mocker.patch.object(slurmd, "is_installed", return_value=True)

            state = manager.run()

        assert state.unit_status == expected

    @pytest.mark.parametrize(
        "params",
        (
            pytest.param(
                {"parameters": "nodeport=427", "reset": True},
                id="invalid config",
            ),
            pytest.param(
                {"parameters": "nodename=compute-0 port=67", "reset": True},
                id="override charm managed config",
            ),
            pytest.param(
                {"parameters": "weight=200", "reset": True},
                id="reset custom config",
            ),
            pytest.param(
                {"parameters": "realmemory=3072", "reset": False},
                id="merge custom config",
            ),
        ),
    )
    def test_on_set_node_config_action(self, mock_charm, params, leader) -> None:
        """Test the `_on_set_node_config_action` action event handler."""
        with mock_charm(
            mock_charm.on.action("set-node-config", params=params),
            testing.State(leader=leader),
        ) as manager:
            try:
                manager.run()
                assert mock_charm.action_results == {"accepted": True}
            except testing.ActionFailed:
                assert mock_charm.action_results == {"accepted": False}
