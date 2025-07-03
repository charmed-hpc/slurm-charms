#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
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

"""Unit tests for the Slurm service operation managers."""

import base64
import subprocess
import textwrap

import pytest
from constants import (
    FAKE_GROUP,
    FAKE_USER,
    JWT_KEY,
    SLURM_KEY_BASE64,
    SLURM_SNAP_INFO_ACTIVE,
    SLURM_SNAP_INFO_INACTIVE,
)
from dotenv import dotenv_values
from pyfakefs.fake_filesystem import FakeFilesystem
from pytest_mock import MockerFixture
from slurm_ops import (
    SackdManager,
    SlurmctldManager,
    SlurmdbdManager,
    SlurmdManager,
    SlurmrestdManager,
)
from slurm_ops.core import SlurmManager
from slurmutils import Node

services = ["sackd", "slurmctld", "slurmd", "slurmdbd", "slurmrestd"]


@pytest.mark.parametrize(
    "snap_backend",
    (
        pytest.param(False, id="apt backend"),
        pytest.param(True, id="snap backend"),
    ),
)
class TestManager:
    """Test Slurm service manager classes."""

    @pytest.fixture(
        params=zip(
            [SackdManager, SlurmctldManager, SlurmdManager, SlurmdbdManager, SlurmrestdManager],
            services,
        ),
        ids=["sackd", "slurmctld", "slurmd", "slurmdbd", "slurmrestd"],
    )
    def mock_manager(self, request, snap_backend) -> tuple[SlurmManager, str]:
        """Request a mocked Slurm service manager and service name."""
        return request.param[0](snap=snap_backend), request.param[1]

    @pytest.fixture
    def mock_slurm_key(self, fs: FakeFilesystem, mock_manager, snap_backend) -> SlurmManager:
        """Request a Slurm service manager with a fake `slurm.key` secret file."""
        if snap_backend:
            fs.create_file("/var/snap/slurm/common/etc/slurm/slurm.key")
        else:
            fs.create_file("/etc/slurm/slurm.key")

        manager, _ = mock_manager
        manager.key._user = FAKE_USER
        manager.key._group = FAKE_GROUP
        manager.key._file.write_bytes(base64.b64decode(SLURM_KEY_BASE64))
        return manager

    @pytest.fixture
    def mock_jwt_key(self, fs: FakeFilesystem, mock_manager, snap_backend) -> SlurmManager:
        """Request a Slurm service manager with a fake `jwt_hs256.key` secret file."""
        if snap_backend:
            fs.create_file("/var/snap/slurm/common/var/lib/slurm/checkpoint/jwt_hs256.key")
        else:
            fs.create_file("/var/lib/slurm/checkpoint/jwt_hs256.key")

        manager, _ = mock_manager
        manager.jwt._user = FAKE_USER
        manager.jwt._group = FAKE_GROUP
        manager.jwt._file.write_text(JWT_KEY)
        return manager

    # Test `<manager>.service` component.

    def test_service_start(self, mock_manager, mock_run, snap_backend) -> None:
        """Test the `<manager>.service.start()` method."""
        manager, service = mock_manager

        manager.service.start()
        if snap_backend:
            assert mock_run.call_args[0][0] == ["snap", "start", f"slurm.{service}"]
        else:
            assert mock_run.call_args[0][0] == ["systemctl", "start", service]

    def test_service_stop(self, mock_manager, mock_run, snap_backend) -> None:
        """Test the `<manager>.service.stop()` method."""
        manager, service = mock_manager

        manager.service.stop()
        if snap_backend:
            assert mock_run.call_args[0][0] == ["snap", "stop", f"slurm.{service}"]
        else:
            assert mock_run.call_args[0][0] == ["systemctl", "stop", service]

    def test_service_enable(self, mock_manager, mock_run, snap_backend) -> None:
        """Test the `<manager>.service.enable()` method."""
        manager, service = mock_manager

        manager.service.enable()
        if snap_backend:
            assert mock_run.call_args[0][0] == ["snap", "start", "--enable", f"slurm.{service}"]
        else:
            assert mock_run.call_args[0][0] == ["systemctl", "enable", service]

    def test_service_disable(self, mock_manager, mock_run, snap_backend) -> None:
        """Test the `<manager>.service.disable()` method."""
        manager, service = mock_manager

        manager.service.disable()
        if snap_backend:
            assert mock_run.call_args[0][0] == ["snap", "stop", "--disable", f"slurm.{service}"]
        else:
            assert mock_run.call_args[0][0] == ["systemctl", "disable", service]

    def test_service_restart(self, mock_manager, mock_run, snap_backend) -> None:
        """Test the `<manager>.service.restart()` method."""
        manager, service = mock_manager

        manager.service.restart()
        if snap_backend:
            assert mock_run.call_args[0][0] == ["snap", "restart", f"slurm.{service}"]
        else:
            assert mock_run.call_args[0][0] == ["systemctl", "restart", service]

    @pytest.mark.parametrize(
        "active",
        (
            pytest.param(True, id="active"),
            pytest.param(False, id="not active"),
        ),
    )
    def test_service_is_active(self, mock_manager, mock_run, snap_backend, active) -> None:
        """Test the `<manager>.service.is_active()` method."""
        manager, service = mock_manager

        if snap_backend:
            mock_run.return_value = (
                subprocess.CompletedProcess([], returncode=0, stdout=SLURM_SNAP_INFO_ACTIVE)
                if active
                else subprocess.CompletedProcess([], returncode=0, stdout=SLURM_SNAP_INFO_INACTIVE)
            )
        else:
            mock_run.return_value = (
                subprocess.CompletedProcess([], returncode=0)
                if active
                else subprocess.CompletedProcess([], returncode=4)
            )

        status = manager.service.is_active()
        if snap_backend:
            assert mock_run.call_args[0][0] == ["snap", "info", "slurm"]
            assert status == active
        else:
            assert mock_run.call_args[0][0] == ["systemctl", "is-active", "--quiet", service]
            assert status == active

    # Test `<manager>.key` component.

    def test_get_slurm_key(self, mock_slurm_key) -> None:
        """Test the `<manager>.key.get()` method."""
        assert mock_slurm_key.key.get() == SLURM_KEY_BASE64

    def test_set_slurm_key(self, mock_slurm_key) -> None:
        """Test the `<manager>.key.set(...)` method."""
        mock_slurm_key.key.set(SLURM_KEY_BASE64)
        assert mock_slurm_key.key.get() == SLURM_KEY_BASE64

    def test_generate_slurm_key(self, mock_slurm_key) -> None:
        """Test the `<manager>.key.generate()` method."""
        mock_slurm_key.key.generate()
        key = base64.b64encode(mock_slurm_key.key.path.read_bytes()).decode()
        assert mock_slurm_key.key.get() == key

    # Test `<manager>.jwt` component.

    def test_get_jwt_key(self, mock_jwt_key) -> None:
        """Test the `<manager>.jwt.get()` method."""
        assert mock_jwt_key.jwt.get() == JWT_KEY

    def test_set_jwt_key(self, mock_jwt_key) -> None:
        """Test the `<manager>.jwt.set(...)` method."""
        mock_jwt_key.jwt.set(JWT_KEY)
        assert mock_jwt_key.jwt.get() == JWT_KEY

    def test_generate_jwt_key(self, mock_jwt_key) -> None:
        """Test the `<manager>.jwt.generate()` method."""
        mock_jwt_key.jwt.generate()
        assert mock_jwt_key.jwt.get() != JWT_KEY

    # Test manager properties.

    def test_hostname(self, mocker: MockerFixture, mock_manager) -> None:
        """Test the `<manager>.hostname` property."""
        mock_gethostname = mocker.patch("socket.gethostname")
        manager, _ = mock_manager

        mock_gethostname.return_value = "machine.lxd"
        assert manager.hostname == "machine"

        mock_gethostname.return_value = "yowzah"
        assert manager.hostname == "yowzah"


class TestSackdManager:
    """Test additional behavior of the `SackdManager` class."""

    @pytest.fixture
    def mock_manager(self, fs: FakeFilesystem) -> SackdManager:
        """Request a mocked `SackdManager` instance."""
        fs.create_file("/etc/default/sackd")
        return SackdManager()

    # Test manager properties.

    def test_conf_server(self, mock_manager) -> None:
        """Test the `conf_server` property."""
        # Set new configuration server addresses.
        mock_manager.conf_server = ["host1:6817", "host2:6817"]
        env = dotenv_values("/etc/default/sackd")

        assert mock_manager.conf_server == ["host1:6817", "host2:6817"]
        assert "SACKD_OPTIONS" in env
        assert env["SACKD_OPTIONS"] == "--conf-server host1:6817,host2:6817"

        # Delete configuration server address.
        del mock_manager.conf_server
        env = dotenv_values("/etc/default/sackd")

        assert mock_manager.conf_server == []
        assert "SACKD_OPTIONS" in env
        assert env["SACKD_OPTIONS"] == ""


class TestSlurmdManager:
    """Test additional behavior of the `SlurmdManager` class."""

    @pytest.fixture
    def mock_manager(self, fs: FakeFilesystem) -> SlurmdManager:
        """Request a mocked `SackdManager` instance."""
        fs.create_file("/etc/default/slurmd")
        return SlurmdManager()

    # Test manager properties.

    def test_conf(self, mock_manager) -> None:
        """Test the `conf` property."""
        # Set new node configuration.
        mock_node = Node()
        mock_node.real_memory = 16000
        mock_node.cpus = 8
        mock_node.gres = ["gpu:tesla_t4:8"]
        mock_manager.conf = mock_node
        env = dotenv_values("/etc/default/slurmd")

        assert mock_manager.conf.dict() == {
            "realmemory": 16000,
            "cpus": 8,
            "gres": ["gpu:tesla_t4:8"],
        }
        assert "SLURMD_OPTIONS" in env
        assert env["SLURMD_OPTIONS"] == "--conf 'realmemory=16000 cpus=8 gres=gpu:tesla_t4:8'"

        # Delete node configuration.
        del mock_manager.conf
        env = dotenv_values("/etc/default/slurmd")

        assert mock_manager.conf.dict() == {}
        assert "SLURMD_OPTIONS" in env
        assert env["SLURMD_OPTIONS"] == ""

    def test_conf_server(self, mock_manager) -> None:
        """Test the `conf_server` property."""
        # Set new configuration server addresses.
        mock_manager.conf_server = ["host1:6817", "host2:6817"]
        env = dotenv_values("/etc/default/slurmd")

        assert mock_manager.conf_server == ["host1:6817", "host2:6817"]
        assert "SLURMD_OPTIONS" in env
        assert env["SLURMD_OPTIONS"] == "--conf-server host1:6817,host2:6817"

        # Delete configuration server address.
        del mock_manager.conf_server
        env = dotenv_values("/etc/default/slurmd")

        assert mock_manager.conf_server == []
        assert "SLURMD_OPTIONS" in env
        assert env["SLURMD_OPTIONS"] == ""

    def test_dynamic(self, mock_manager) -> None:
        """Test the `dynamic` property."""
        # Mark node as dynamic.
        mock_manager.dynamic = True
        env = dotenv_values("/etc/default/slurmd")

        assert mock_manager.dynamic is True
        assert "SLURMD_OPTIONS" in env
        assert env["SLURMD_OPTIONS"] == "-Z"

        # Unmark node as dynamic.
        mock_manager.dynamic = False
        env = dotenv_values("/etc/default/slurmd")

        assert mock_manager.dynamic is False
        assert "SLURMD_OPTIONS" in env
        assert env["SLURMD_OPTIONS"] == ""


class TestSlurmdbdManager:
    """Test additional behavior of the `SlurmdbdManager` class."""

    @pytest.fixture
    def mock_manager(self, fs: FakeFilesystem) -> SlurmdbdManager:
        """Request a mocked `SackdManager` instance."""
        fs.create_file(
            "/etc/default/slurmdbd",
            contents=textwrap.dedent(
                """
                MYSQL_UNIX_PORT="/var/run/mysql/mysql.sock"
                """
            ),
        )
        return SlurmdbdManager()

    # Test manager properties.

    def test_mysql_unix_port(self, mock_manager) -> None:
        """Test the `mysql_unix_port` property."""
        # Get the path to MySQL unix port.
        assert mock_manager.mysql_unix_port == "/var/run/mysql/mysql.sock"

        # Set the path to MySQL unix port.
        mock_manager.mysql_unix_port = "/var/snap/mysql/common/run/mysql/mysql.sock"
        env = dotenv_values("/etc/default/slurmdbd")

        assert mock_manager.mysql_unix_port == "/var/snap/mysql/common/run/mysql/mysql.sock"
        assert "MYSQL_UNIX_PORT" in env
        assert env["MYSQL_UNIX_PORT"] == "/var/snap/mysql/common/run/mysql/mysql.sock"

        # Unset the path to the MySQL unix port.
        del mock_manager.mysql_unix_port
        env = dotenv_values("/etc/default/slurmdbd")

        assert mock_manager.mysql_unix_port is None
        assert "MYSQL_UNIX_PORT" not in env
