#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
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

"""Test default charm events such as upgrade charm, install, etc."""

import unittest
from unittest.mock import Mock, patch

import ops.testing
from charm import SlurmdbdCharm
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

ops.testing.SIMULATE_CAN_CONNECT = True


class TestCharm(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(SlurmdbdCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch("slurmdbd_ops.SlurmdbdOpsManager.install", return_value=True)
    @patch("slurmdbd_ops.SlurmdbdOpsManager.start_munge", return_value=True)
    def test_install_success(self, *_) -> None:
        """Test that slurmdbd can successfully be installed.

        Notes:
            This method is expected to fail due to the 'version' file missing.
        """
        self.harness.set_leader(True)
        self.harness.charm._stored.db_info = {"rats": "123"}
        self.harness.charm.on.install.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("slurmdbd_ops.SlurmdbdOpsManager.install", return_value=False)
    def test_install_fail(self, install) -> None:
        """Test that slurmdbd install fail handler works."""
        self.harness.set_leader(True)
        self.harness.charm.on.install.emit()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Error installing slurmdbd.")
        )

    @patch("slurmdbd_ops.SlurmdbdOpsManager.install")
    def test_check_status_slurm_not_installed(self, install) -> None:
        """Test that _check_status method works if slurm is not installed."""
        self.harness.charm._stored.slurm_installed = False
        res = self.harness.charm._check_status()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Error installing slurmdbd.")
        )
        self.assertFalse(
            res, msg="_check_status returned value True instead of expected value False."
        )

    @patch("slurmdbd_ops.SlurmdbdOpsManager.install")
    @patch("slurmdbd_ops.SlurmdbdOpsManager.restart_slurmdbd")
    @patch("slurmdbd_ops.SlurmdbdOpsManager.is_slurmdbd_active", return_value=True)
    def test_check_slurmdbd(self, *_) -> None:
        """Test that _check_slurmdbd method works."""
        self.harness.charm._check_slurmdbd(max_attemps=1)
        self.assertNotEqual(
            self.harness.charm.unit.status, BlockedStatus("Cannot start slurmdbd.")
        )

    @patch("charm.sleep")
    @patch("slurmdbd_ops.SlurmdbdOpsManager.install")
    @patch("slurmdbd_ops.SlurmdbdOpsManager.restart_slurmdbd")
    @patch("slurmdbd_ops.SlurmdbdOpsManager.is_slurmdbd_active", return_value=False)
    def test_check_slurmdbd_slurm_not_active(self, *_) -> None:
        """Test that proper block status is thrown if slurm is not active."""
        self.harness.charm._stored.slurm_installed = True
        self.harness.charm._stored.db_info = {
            "StorageUser": "fake-user",
            "StoragePass": "fake-password",
            "StorageLoc": "slurm_acct_db",
        }
        self.harness.charm._check_slurmdbd(max_attemps=1)
        self.assertEqual(self.harness.charm.unit.status, BlockedStatus("Cannot start slurmdbd."))

    def test__on_database_created_no_endpoints(self, *_) -> None:
        """Tests that the on_database_created method errors with no endpoints."""
        self.harness.set_leader(True)
        event = Mock()
        event.endpoints = None
        self.assertRaises(ValueError, self.harness.charm._on_database_created, event)
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("No database endpoints provided")
        )

        event.endpoints = ""
        self.assertRaises(ValueError, self.harness.charm._on_database_created, event)
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("No database endpoints provided")
        )

        event.endpoints = " , "
        self.assertRaises(ValueError, self.harness.charm._on_database_created, event)
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("No database endpoints provided")
        )

    @patch("charm.SlurmdbdCharm._write_config_and_restart_slurmdbd")
    @patch("slurmdbd_ops.SlurmdbdOpsManager.set_environment_var")
    def test__on_database_created_socket_endpoints(
        self, _set_environment_var, _write_config_and_restart_slurmdbd
    ) -> None:
        """Tests socket endpoints update the environment file."""
        event = Mock()
        event.endpoints = "file:///path/to/some/socket"
        event.username = "fake-user"
        event.password = "fake-password"

        self.harness.charm._on_database_created(event)

        _set_environment_var.assert_called_once_with(mysql_unix_port='"/path/to/some/socket"')
        db_info = {
            "StorageUser": "fake-user",
            "StoragePass": "fake-password",
            "StorageLoc": "slurm_acct_db",
        }
        self.assertEqual(self.harness.charm._stored.db_info, db_info)
        _write_config_and_restart_slurmdbd.assert_called_once_with(event)

    @patch("charm.SlurmdbdCharm._write_config_and_restart_slurmdbd")
    @patch("slurmdbd_ops.SlurmdbdOpsManager.set_environment_var")
    def test__on_database_created_socket_multiple_endpoints(
        self, _set_environment_var, _write_config_and_restart_slurmdbd
    ) -> None:
        """Tests multiple socket endpoints only uses one endpoint."""
        event = Mock()
        event.username = "fake-user"
        event.password = "fake-password"
        # Note: also include some whitespace just to check.
        event.endpoints = " file:///some/other/path, file:///path/to/some/socket "

        self.harness.charm._on_database_created(event)

        _set_environment_var.assert_called_once_with(mysql_unix_port='"/some/other/path"')
        db_info = {
            "StorageUser": "fake-user",
            "StoragePass": "fake-password",
            "StorageLoc": "slurm_acct_db",
        }
        self.assertEqual(self.harness.charm._stored.db_info, db_info)
        _write_config_and_restart_slurmdbd.assert_called_once_with(event)

    @patch("charm.SlurmdbdCharm._write_config_and_restart_slurmdbd")
    @patch("slurmdbd_ops.SlurmdbdOpsManager.set_environment_var")
    def test__on_database_created_tcp_endpoint(
        self, _set_environment_var, _write_config_and_restart_slurmdbd
    ) -> None:
        """Tests tcp endpoint for database."""
        event = Mock()
        event.endpoints = "10.2.5.20:1234"
        event.username = "fake-user"
        event.password = "fake-password"

        self.harness.charm._on_database_created(event)

        _set_environment_var.assert_called_once_with(mysql_unix_port=None)
        db_info = {
            "StorageUser": "fake-user",
            "StoragePass": "fake-password",
            "StorageLoc": "slurm_acct_db",
            "StorageHost": "10.2.5.20",
            "StoragePort": "1234",
        }
        self.assertEqual(self.harness.charm._stored.db_info, db_info)
        _write_config_and_restart_slurmdbd.assert_called_once_with(event)

    @patch("charm.SlurmdbdCharm._write_config_and_restart_slurmdbd")
    @patch("slurmdbd_ops.SlurmdbdOpsManager.set_environment_var")
    def test__on_database_created_multiple_tcp_endpoints(
        self, _set_environment_var, _write_config_and_restart_slurmdbd
    ) -> None:
        """Tests multiple tcp endpoints for the database."""
        event = Mock()
        # Note: odd spacing to test split logic as well
        event.endpoints = "10.2.5.20:1234 ,10.2.5.21:1234, 10.2.5.21:1234"
        event.username = "fake-user"
        event.password = "fake-password"

        self.harness.charm._on_database_created(event)

        _set_environment_var.assert_called_once_with(mysql_unix_port=None)
        db_info = {
            "StorageUser": "fake-user",
            "StoragePass": "fake-password",
            "StorageLoc": "slurm_acct_db",
            "StorageHost": "10.2.5.20",
            "StoragePort": "1234",
        }
        self.assertEqual(self.harness.charm._stored.db_info, db_info)
        _write_config_and_restart_slurmdbd.assert_called_once_with(event)

    @patch("slurmdbd_ops.SlurmdbdOpsManager.install", return_value=True)
    @patch("charm.SlurmdbdCharm._write_config_and_restart_slurmdbd")
    @patch("slurmdbd_ops.SlurmdbdOpsManager.set_environment_var")
    def test__on_database_created_ipv6_tcp_endpoints(
        self,
        _set_environment_var,
        _write_config_and_restart_slurmdbd,
        *_,
    ) -> None:
        """Tests multiple tcp endpoints for the database."""
        event = Mock()
        # Note: odd spacing to test split logic as well
        event.endpoints = (
            "[9ee0:49d9:465c:8fd4:c5ef:f596:73ef:0c4e]:1234 ,"
            "[e7d5:2c42:8074:8c51:d0ca:af6a:488e:f333]:1234, "
            "[e923:bb41:3db3:1884:a97e:d16e:dc51:271e]:1234"
        )
        event.username = "fake-user"
        event.password = "fake-password"

        self.harness.charm._on_database_created(event)

        _set_environment_var.assert_called_once_with(mysql_unix_port=None)
        db_info = {
            "StorageUser": "fake-user",
            "StoragePass": "fake-password",
            "StorageLoc": "slurm_acct_db",
            "StorageHost": "9ee0:49d9:465c:8fd4:c5ef:f596:73ef:0c4e",
            "StoragePort": "1234",
        }
        self.assertEqual(self.harness.charm._stored.db_info, db_info)
        _write_config_and_restart_slurmdbd.assert_called_once_with(event)
