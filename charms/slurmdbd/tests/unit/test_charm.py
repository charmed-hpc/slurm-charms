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

from unittest.mock import Mock, PropertyMock, patch

from charm import SlurmdbdCharm
from hpc_libs.slurm_ops import SlurmOpsError
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness
from pyfakefs.fake_filesystem_unittest import TestCase


class TestCharm(TestCase):
    def setUp(self) -> None:
        self.harness = Harness(SlurmdbdCharm)
        self.addCleanup(self.harness.cleanup)
        self.setUpPyfakefs()
        self.harness.begin()

    @patch("interface_slurmctld.Slurmctld.is_joined", new_callable=PropertyMock)
    def test_install_success(self, is_joined) -> None:
        """Test `InstallEvent` hook success."""
        self.harness.set_leader(True)
        is_joined.return_value = True

        # Patch jwt.path.exists on the instance
        mock_jwt = Mock()
        mock_jwt.path.exists.return_value = True
        self.harness.charm._slurmdbd.jwt = mock_jwt

        self.harness.charm._slurmdbd.install = Mock()
        self.harness.charm._slurmdbd.service.enable = Mock()
        self.harness.charm._slurmdbd.version = Mock(return_value="24.05.2.-1")

        self.harness.charm._stored.db_info = {"rats": "123"}
        self.harness.charm._stored.slurm_installed = True

        self.harness.charm.on.install.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("ops.framework.EventBase.defer")
    def test_install_fail_ha_support(self, defer) -> None:
        """Test `InstallEvent` hook failure when there are multiple slurmdbd units.

        Notes:
            The slurmdbd charm currently does not support high-availability so this
            unit test validates that we properly handle if multiple slurmdbd units
            are deployed.
        """
        self.harness.set_leader(False)
        self.harness.charm.on.install.emit()

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus(
                "slurmdbd high-availability not supported. see logs for further details"
            ),
        )
        defer.assert_called()

    @patch("ops.framework.EventBase.defer")
    def test_install_fail_slurmdbd_package(self, defer) -> None:
        """Test `InstallEvent` hook when slurmdbd fails to install."""
        self.harness.set_leader(True)
        self.harness.charm._slurmdbd.install = Mock(
            side_effect=SlurmOpsError("failed to install slurmd")
        )
        self.harness.charm.on.install.emit()

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("failed to install slurmdbd. see logs for further details"),
        )
        defer.assert_called()

    def test_update_status_fail(self) -> None:
        """Test `UpdateStatusEvent` on failed install."""
        self.harness.set_leader(True)
        self.harness.charm.on.update_status.emit()

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("failed to install slurmdbd. see logs for further details"),
        )

    @patch("interface_slurmctld.Slurmctld.is_joined", new_callable=PropertyMock)
    def test_status_blocked_on_missing_slurmctld_relation(self, is_joined) -> None:
        """Test that BlockedStatus is set when slurmctld relation is missing."""
        self.harness.set_leader(True)
        is_joined.return_value = False

        self.harness.charm._slurmdbd.install = Mock()
        self.harness.charm._slurmdbd.service.enable = Mock()
        self.harness.charm._slurmdbd.version = Mock(return_value="24.05.2.-1")

        self.harness.charm._stored.db_info = {"rats": "123"}
        self.harness.charm._stored.slurm_installed = True

        self.harness.charm.on.install.emit()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Need relations: slurmctld")
        )

    @patch("interface_slurmctld.Slurmctld.is_joined", new_callable=PropertyMock)
    def test_status_waiting_on_missing_jwt_key_relation_data(self, is_joined) -> None:
        """Test that WaitingStatus is set when slurmctld is related but relation data has not been received."""
        self.harness.set_leader(True)
        is_joined.return_value = True

        # Patch jwt.path.exists on the instance
        mock_jwt = Mock()
        mock_jwt.path.exists.return_value = False
        self.harness.charm._slurmdbd.jwt = mock_jwt

        self.harness.charm._slurmdbd.install = Mock()
        self.harness.charm._slurmdbd.service.enable = Mock()
        self.harness.charm._slurmdbd.version = Mock(return_value="24.05.2.-1")

        self.harness.charm._stored.db_info = {"rats": "123"}
        self.harness.charm._stored.slurm_installed = True

        self.harness.charm.on.install.emit()
        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("Waiting on: data from slurmctld...")
        )

    @patch("interface_slurmctld.Slurmctld.is_joined", new_callable=PropertyMock)
    def test_status_waiting_on_mysql(self, is_joined) -> None:
        """Test charm status when mysql isn't yet related and no user supplied db-uri."""
        self.harness.set_leader(True)
        is_joined.return_value = True

        # Patch jwt.path.exists on the instance
        mock_jwt = Mock()
        mock_jwt.path.exists.return_value = True
        self.harness.charm._slurmdbd.jwt = mock_jwt

        self.harness.charm._slurmdbd.install = Mock()
        self.harness.charm._slurmdbd.service.enable = Mock()
        self.harness.charm._slurmdbd.version = Mock(return_value="24.05.2.-1")
        self.harness.charm._get_db_info = Mock(return_value={})

        self.harness.charm._stored.slurm_installed = True

        self.harness.charm.on.install.emit()
        self.assertEqual(self.harness.charm.unit.status, WaitingStatus("Waiting on: MySQL"))

    @patch("charm.sleep")
    def test_check_slurmdbd(self, *_) -> None:
        """Test that `BlockedStatus` is set when slurmdbd service is not running."""
        self.harness.charm._slurmdbd.service.active = Mock(return_value=False)
        self.harness.charm._slurmdbd.service.restart = Mock()
        self.harness.charm._check_slurmdbd(max_attemps=1)

        self.assertEqual(self.harness.charm.unit.status, BlockedStatus("cannot start slurmdbd"))

    def test_on_database_created_no_endpoints(self, *_) -> None:
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
    @patch("hpc_libs.slurm_ops.SlurmdbdManager.mysql_unix_port", new_callable=PropertyMock)
    def test_on_database_created_socket_endpoints(
        self, mysql_unix_port, _write_config_and_restart_slurmdbd
    ) -> None:
        """Tests socket endpoints update the environment file."""
        event = Mock()
        event.endpoints = "file:///path/to/some/socket"
        event.username = "fake-user"
        event.password = "fake-password"

        self.harness.charm._on_database_created(event)

        mysql_unix_port.assert_called_once_with("/path/to/some/socket")
        db_info = {
            "StorageUser": "fake-user",
            "StoragePass": "fake-password",
            "StorageLoc": "slurm_acct_db",
        }
        self.assertEqual(self.harness.charm._stored.db_info, db_info)
        _write_config_and_restart_slurmdbd.assert_called_once_with(event)

    @patch("charm.SlurmdbdCharm._write_config_and_restart_slurmdbd")
    @patch("hpc_libs.slurm_ops.SlurmdbdManager.mysql_unix_port", new_callable=PropertyMock)
    def test_on_database_created_socket_multiple_endpoints(
        self, mysql_unix_port, _write_config_and_restart_slurmdbd
    ) -> None:
        """Tests multiple socket endpoints only uses one endpoint."""
        event = Mock()
        event.username = "fake-user"
        event.password = "fake-password"
        # Note: also include some whitespace just to check.
        event.endpoints = " file:///some/other/path, file:///path/to/some/socket "

        self.harness.charm._on_database_created(event)

        mysql_unix_port.assert_called_once_with("/some/other/path")
        db_info = {
            "StorageUser": "fake-user",
            "StoragePass": "fake-password",
            "StorageLoc": "slurm_acct_db",
        }
        self.assertEqual(self.harness.charm._stored.db_info, db_info)
        _write_config_and_restart_slurmdbd.assert_called_once_with(event)

    @patch("charm.SlurmdbdCharm._write_config_and_restart_slurmdbd")
    @patch("hpc_libs.slurm_ops.SlurmdbdManager.mysql_unix_port", new_callable=PropertyMock)
    def test_on_database_created_tcp_endpoint(
        self, mysql_unix_port, _write_config_and_restart_slurmdbd
    ) -> None:
        """Tests tcp endpoint for database."""
        mysql_unix_port.__delete__ = Mock()
        event = Mock()
        event.endpoints = "10.2.5.20:1234"
        event.username = "fake-user"
        event.password = "fake-password"

        self.harness.charm._on_database_created(event)

        mysql_unix_port.__delete__.assert_called_once()
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
    @patch("hpc_libs.slurm_ops.SlurmdbdManager.mysql_unix_port", new_callable=PropertyMock)
    def test_on_database_created_multiple_tcp_endpoints(
        self, mysql_unix_port, _write_config_and_restart_slurmdbd
    ) -> None:
        """Tests multiple tcp endpoints for the database."""
        mysql_unix_port.__delete__ = Mock()
        event = Mock()
        # Note: odd spacing to test split logic as well
        event.endpoints = "10.2.5.20:1234 ,10.2.5.21:1234, 10.2.5.21:1234"
        event.username = "fake-user"
        event.password = "fake-password"

        self.harness.charm._on_database_created(event)

        mysql_unix_port.__delete__.assert_called_once()
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
    @patch("hpc_libs.slurm_ops.SlurmdbdManager.mysql_unix_port", new_callable=PropertyMock)
    def test_on_database_created_ipv6_tcp_endpoints(
        self,
        mysql_unix_port,
        _write_config_and_restart_slurmdbd,
        *_,
    ) -> None:
        """Tests multiple tcp endpoints for the database."""
        mysql_unix_port.__delete__ = Mock()
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

        mysql_unix_port.__delete__.assert_called_once()
        db_info = {
            "StorageUser": "fake-user",
            "StoragePass": "fake-password",
            "StorageLoc": "slurm_acct_db",
            "StorageHost": "9ee0:49d9:465c:8fd4:c5ef:f596:73ef:0c4e",
            "StoragePort": "1234",
        }
        self.assertEqual(self.harness.charm._stored.db_info, db_info)
        _write_config_and_restart_slurmdbd.assert_called_once_with(event)

    def test_user_supplied_slurmdbd_conf_parameters(self, *_) -> None:
        """Test that user supplied slurmdbd.conf parameters are parsed correctly."""
        self.harness.add_relation("slurmdbd-peer", self.harness.charm.app.name)

        log_file_val = "/tmp/test.log"
        allow_no_def_acct_val = "yes"

        log_file = f"LogFile={log_file_val}"
        allow_no_def_acct = f"AllowNoDefAcct={allow_no_def_acct_val}"

        user_supplied_slurmdbd_config = "\n".join([log_file, allow_no_def_acct])

        # Set user suppled slurmdbd config already defined by the charm in
        # CHARM_MAINTAINED_SLURMDBD_CONF_PARAMETERS so that we test overriding predefined
        # key,val with user supplied config in addition to setting slurm config that doesn't
        # override any predefined slurmdbd configuration.
        self.harness.update_config({"slurmdbd-conf-parameters": user_supplied_slurmdbd_config})
        self.assertEqual(
            self.harness.charm._assemble_slurmdbd_conf().log_file,
            log_file_val,
        )
        self.assertEqual(
            self.harness.charm._assemble_slurmdbd_conf().allow_no_def_acct,
            allow_no_def_acct_val,
        )
