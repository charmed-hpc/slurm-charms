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

"""Unit tests for the sackd operator."""

from unittest import TestCase
from unittest.mock import Mock, PropertyMock, patch

from charm import SackdCharm
from ops.model import ActiveStatus, BlockedStatus
from scenario import Context, State

from charms.hpc_libs.v0.slurm_ops import SlurmOpsError


class TestCharm(TestCase):
    """Unit test sackd charm."""

    def setUp(self) -> None:
        """Set up unit test."""
        self.ctx = Context(SackdCharm)

    @patch("charms.operator_libs_linux.v0.juju_systemd_notices.SystemdNotices.subscribe")
    @patch("ops.framework.EventBase.defer")
    def test_install_success(self, defer, *_) -> None:
        """Test install success behavior."""
        with self.ctx(self.ctx.on.install(), State()) as manager:
            manager.charm._sackd.install = Mock()
            manager.charm._sackd.service.disable = Mock()
            manager.charm._sackd.version = Mock(return_value="24.05.2-1")
            manager.run()
            self.assertTrue(manager.charm._stored.sackd_installed)

        defer.assert_not_called()

    @patch("ops.framework.EventBase.defer")
    def test_install_fail(self, defer) -> None:
        """Test install failure behavior."""
        with self.ctx(self.ctx.on.install(), State()) as manager:
            manager.charm._sackd.install = Mock(
                side_effect=SlurmOpsError("failed to install sackd")
            )
            manager.run()

            self.assertEqual(
                manager.charm.unit.status,
                BlockedStatus("failed to install sackd. see logs for further details"),
            )
            self.assertFalse(manager.charm._stored.sackd_installed)

        defer.assert_called()

    def test_service_sackd_start(self) -> None:
        """Test service_sackd_started event handler."""
        with self.ctx(self.ctx.on.start(), State()) as manager:
            # Run method directly rather than emit a ServiceStartedEvent.
            # TODO: Refactor once Scenario has restored support for running custom events. See:
            # https://github.com/canonical/operator/issues/1421
            manager.charm._on_sackd_started(None)
            self.assertEqual(manager.charm.unit.status, ActiveStatus())

    def test_service_sackd_stopped(self) -> None:
        """Test service_sackd_stopped event handler."""
        with self.ctx(self.ctx.on.stop(), State()) as manager:
            # Run method directly rather than emit a ServiceStoppedEvent.
            # TODO: Refactor once Scenario has restored support for running custom events. See:
            # https://github.com/canonical/operator/issues/1421
            manager.charm._on_sackd_stopped(None)
            self.assertEqual(manager.charm.unit.status, BlockedStatus("sackd not running"))

    @patch("interface_slurmctld.Slurmctld.is_joined", new_callable=PropertyMock(return_value=True))
    def test_update_status_success(self, *_) -> None:
        """Test `UpdateStateEvent` hook success."""
        with self.ctx(self.ctx.on.update_status(), State()) as manager:
            manager.charm._stored.sackd_installed = True
            manager.charm._stored.slurmctld_available = True
            manager.charm.unit.status = ActiveStatus()
            manager.run()
            # ActiveStatus is the expected value when _check_status does not
            # modify the current state of the unit and should return True.
            self.assertTrue(manager.charm._check_status())
            self.assertEqual(manager.charm.unit.status, ActiveStatus())

    def test_update_status_install_fail(self) -> None:
        """Test `UpdateStateEvent` hook failure."""
        with self.ctx(self.ctx.on.update_status(), State()) as manager:
            manager.run()
            self.assertEqual(
                manager.charm.unit.status,
                BlockedStatus("failed to install sackd. see logs for further details"),
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
