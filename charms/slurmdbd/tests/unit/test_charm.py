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

"""Unit tests for the `slurmdbd` charm."""

import ops
import pytest
from constants import DATABASE_INTEGRATION_NAME, SLURMDBD_INTEGRATION_NAME
from ops import testing
from pytest_mock import MockerFixture
from slurm_ops import SlurmOpsError


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSlurmdbdCharm:
    """Unit tests for the `slurmdbd` charmed operator."""

    @pytest.mark.parametrize(
        "mock_install,expected",
        (
            pytest.param(
                None,
                ops.BlockedStatus("Waiting for integrations: [`slurmctld`, `database`]"),
                id="success",
            ),
            pytest.param(
                SlurmOpsError("install failed"),
                ops.BlockedStatus(
                    "Failed to install `slurmdbd`. See `juju debug-log` for details."
                ),
                id="fail",
            ),
        ),
    )
    def test_on_install(
        self,
        mock_charm,
        mocker: MockerFixture,
        mock_install,
        leader,
        expected,
    ) -> None:
        """Test the `_on_install` event handler."""
        with mock_charm(mock_charm.on.install(), testing.State(leader=leader)) as manager:
            slurmdbd = manager.charm.slurmdbd
            mocker.patch.object(slurmdbd, "install", side_effect=mock_install)
            mocker.patch.object(slurmdbd, "is_installed")
            mocker.patch.object(slurmdbd, "version", return_value="24.05.2-1")
            mocker.patch.object(slurmdbd.service, "stop")
            mocker.patch.object(slurmdbd.service, "disable")
            mocker.patch.object(slurmdbd.service, "is_active", return_value=False)

            state = manager.run()

        if leader:
            assert state.unit_status == expected
        else:
            assert state.unit_status == ops.BlockedStatus(
                "`slurmdbd` high-availability is not supported. Scale down application"
            )

    def test_on_config_changed(
        self,
        mock_charm,
        mocker: MockerFixture,
        peer_integration,
        leader,
    ) -> None:
        """Test the `_on_config_changed` event handler."""
        with mock_charm(
            mock_charm.on.config_changed(),
            testing.State(leader=leader, relations={peer_integration}),
        ) as manager:
            slurmdbd = manager.charm.slurmdbd
            mocker.patch.object(slurmdbd, "is_installed", return_value=True)
            mocker.patch.object(slurmdbd.service, "is_active", return_value=False)

            manager.run()

        if leader:
            assert slurmdbd.config.path.exists()
        else:
            assert not slurmdbd.config.path.exists()

    def test_reconfigure(
        self,
        mock_charm,
        mocker: MockerFixture,
        peer_integration,
        leader,
        succeed,
    ) -> None:
        """Test the `_reconfigure` method."""
        slurmctld_integration = testing.Relation(
            endpoint=SLURMDBD_INTEGRATION_NAME,
            interface="slurmdbd",
        )
        database_integration = testing.Relation(
            endpoint=DATABASE_INTEGRATION_NAME,
            interface="mysql_client",
        )

        with mock_charm(
            mock_charm.on.config_changed(),
            testing.State(
                leader=leader,
                relations={peer_integration, slurmctld_integration, database_integration},
            ),
        ) as manager:
            slurmdbd = manager.charm.slurmdbd
            mocker.patch.object(slurmdbd, "is_installed", return_value=True)
            mocker.patch.object(slurmdbd.service, "is_active", return_value=True)
            mocker.patch("charm.slurmdbd_ready", return_value=True)

            mock_reconfigure = mocker.patch.object(slurmdbd, "reconfigure")
            if not succeed:
                mock_reconfigure.side_effect = SlurmOpsError("reconfigure failed")

            state = manager.run()

        if not leader:
            mock_reconfigure.assert_not_called()
        elif succeed:
            mock_reconfigure.assert_called_once()
            assert state.unit_status == ops.ActiveStatus()
        else:
            mock_reconfigure.assert_called_once()
            assert state.unit_status == ops.BlockedStatus(
                "Failed to apply updated `slurmdbd` configuration. "
                "See `juju debug-log` for details"
            )
