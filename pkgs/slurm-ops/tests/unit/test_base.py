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

"""Unit tests for the classes and functions in the `slurm_ops.core.base` module."""

import stat
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess

import pytest
from constants import (
    SLURM_APT_INFO,
    SLURM_SNAP_INFO_ACTIVE,
    SLURM_SNAP_INFO_NOT_INSTALLED,
    ULIMIT_CONFIG,
)
from hpc_libs.machine import apt
from pyfakefs.fake_filesystem import FakeFilesystem
from pytest_mock import MockerFixture
from slurm_ops import (
    SackdManager,
    SlurmctldManager,
    SlurmdbdManager,
    SlurmdManager,
    SlurmOpsError,
    SlurmrestdManager,
)
from slurm_ops.core import SlurmManager

services = ["sackd", "slurmctld", "slurmd", "slurmdbd", "slurmrestd"]


class TestAptManager:
    """Unit tests for the `_AptManager` class."""

    @pytest.fixture(
        params=zip(
            [SackdManager, SlurmctldManager, SlurmdManager, SlurmdbdManager, SlurmrestdManager],
            services,
        ),
        ids=services,
    )
    def mock_manager(self, request, fs: FakeFilesystem) -> tuple[SlurmManager, str]:
        """Request a mocked Slurm service manager and service name."""
        fs.create_dir("/etc/default")
        fs.create_dir("/etc/security/limits.d")
        fs.create_dir("/etc/systemd/service/slurmctld.service.d")
        fs.create_dir("/etc/systemd/service/slurmd.service.d")
        fs.create_dir("/usr/lib/systemd/system")
        fs.create_dir("/var/lib/slurm")

        return request.param[0](), request.param[1]

    def test_install(self, mock_manager, mocker: MockerFixture) -> None:
        """Test the `install` method."""
        manager, _ = mock_manager
        mocker.patch("slurm_ops.core.base._AptManager._init_ubuntu_hpc_ppa")
        mocker.patch("slurm_ops.core.base._AptManager._install_service")
        mocker.patch("slurm_ops.core.base._AptManager._apply_overrides")
        mocker.patch("shutil.chown")

        manager.install()
        f_info = Path("/var/lib/slurm").stat()
        assert stat.filemode(f_info.st_mode) == "drwxr-xr-x"
        f_info = Path("/var/lib/slurm/checkpoint").stat()
        assert stat.filemode(f_info.st_mode) == "drwxr-xr-x"

    def test_version(self, mock_manager, mock_run) -> None:
        """Test the `version` method."""
        manager, service = mock_manager

        # Test `version` when the Slurm service is installed.
        mock_run.side_effect = [
            CompletedProcess([], returncode=0, stdout="amd64"),
            CompletedProcess([], returncode=0, stdout=SLURM_APT_INFO.substitute(service=service)),
        ]

        assert manager.version() == "23.11.7-2ubuntu1"
        assert mock_run.call_args[0][0] == ["dpkg", "-l", service]

        # Test `version` when the Slurm service is not installed.
        mock_run.side_effect = [
            CompletedProcess([], returncode=0, stdout="amd64"),
            CompletedProcess([], returncode=1),
        ]

        with pytest.raises(SlurmOpsError) as exec_info:
            manager.version()

        assert exec_info.type == SlurmOpsError
        assert exec_info.value.message == (
            f"unable to retrieve {service} version. "
            + f"reason: Package {service}.amd64 is not installed!"
        )

    def test_is_installed(self, mock_manager, mock_run) -> None:
        """Test the `is_installed` method."""
        manager, service = mock_manager

        # Test `is_installed` when the Slurm service is installed.
        mock_run.side_effect = [
            CompletedProcess([], returncode=0, stdout="amd64"),
            CompletedProcess([], returncode=0, stdout=SLURM_APT_INFO.substitute(service=service)),
        ]

        assert manager.is_installed() is True

        # Test `is_installed` when the Slurm service is not installed.
        mock_run.side_effect = [
            CompletedProcess([], returncode=0, stdout="amd64"),
            CompletedProcess([], returncode=1),
        ]

        assert manager.is_installed() is False

    def test_init_ubuntu_hpc_ppa(self, mock_manager, mocker: MockerFixture, mock_run) -> None:
        """Test the `_init_ubuntu_hpc_ppa` helper method."""
        manager, _ = mock_manager
        mocker.patch("hpc_libs.machine.apt.DebianRepository._get_keyid_by_gpg_key")
        mocker.patch("hpc_libs.machine.apt.DebianRepository._dearmor_gpg_key")
        mocker.patch("hpc_libs.machine.apt.DebianRepository._write_apt_gpg_keyfile")
        mocker.patch("distro.codename", return_value="noble")

        # Test that Ubuntu HPC PPA is successfully added to the sources list.
        manager._ops_manager._init_ubuntu_hpc_ppa()
        expected = [
            "add-apt-repository",
            "--yes",
            (
                "--sourceslist="
                + "deb https://ppa.launchpadcontent.net/ubuntu-hpc/experimental/ubuntu noble main"
            ),
            "--no-update",
        ]
        # The first call of `mock_run` is sometimes `lsb_release -a` and not
        # `add-apt-repository ...`. Tried using `ripgrep` to find where `lsb_release -a` is called,
        # and why it is only called occasionally, but not results came up.
        assert (
            mock_run.call_args_list[1][0][0] == expected
            or mock_run.call_args_list[0][0][0] == expected
        )

        # Test that a `SlurmOpsError` is raised if an error occurs when adding the Ubuntu HPC PPA.
        mock_run.side_effect = CalledProcessError(
            cmd="add-apt-repository --yes --sourceslist=...",
            returncode=1,
            stderr=b"failed to add ppa",
            output=b"",
        )
        with pytest.raises(SlurmOpsError) as exec_info:
            manager._ops_manager._init_ubuntu_hpc_ppa()

        assert exec_info.type == SlurmOpsError
        assert exec_info.value.message == (
            "failed to initialize apt to use ubuntu hpc repositories. "
            + "reason: Command 'add-apt-repository --yes --sourceslist=...' "
            + "returned non-zero exit status 1."
        )

    def test_set_ulimit(self, mock_manager) -> None:
        """Test the `_set_ulimit` helper method."""
        manager, _ = mock_manager
        manager._ops_manager._set_ulimit()

        target = Path("/etc/security/limits.d/20-charmed-hpc-openfile.conf")
        assert ULIMIT_CONFIG == target.read_text()
        f_info = target.stat()
        assert stat.filemode(f_info.st_mode) == "-rw-r--r--"

    def test_install_service(self, mock_manager, mocker: MockerFixture) -> None:
        """Test the `_install_service` helper method."""
        manager, service = mock_manager
        mock_add_package = mocker.patch.object(apt, "add_package")

        # Test that the correct packages are installed based on the Slurm service being managed.
        manager._ops_manager._install_service()
        match service:
            case "sackd":
                assert mock_add_package.call_args[0][0] == ["sackd", "slurm-client"]

            case "slurmctld":
                assert mock_add_package.call_args[0][0] == [
                    "slurmctld",
                    "libpmix-dev",
                    "mailutils",
                    "prometheus-slurm-exporter",
                ]

            case "slurmd":
                assert mock_add_package.call_args[0][0] == [
                    "slurmd",
                    "slurm-client",
                    "libpmix-dev",
                    "openmpi-bin",
                ]

            case "slurmdbd":
                assert mock_add_package.call_args[0][0] == ["slurmdbd"]

            case "slurmrestd":
                assert mock_add_package.call_args[0][0] == [
                    "slurmrestd",
                    "slurm-wlm-basic-plugins",
                ]

        # Test that a `SlurmOpsError` error is raised if a package fails to install.
        mock_add_package.side_effect = apt.PackageError("failed to install packages")
        with pytest.raises(SlurmOpsError) as exec_info:
            manager._ops_manager._install_service()

        assert exec_info.type == SlurmOpsError
        assert exec_info.value.message == (
            f"failed to install {service}. reason: failed to install packages"
        )

    def test_apply_overrides(self, mock_manager, mock_run) -> None:
        """Test the `_apply_overrides` helper method."""
        manager, service = mock_manager

        manager._ops_manager._apply_overrides()
        match service:
            case "slurmrestd":
                groupadd = mock_run.call_args_list[0][0][0]
                adduser = mock_run.call_args_list[1][0][0]
                systemctl = mock_run.call_args_list[2][0][0]

                assert groupadd == ["groupadd", "--gid", "64031", "slurmrestd"]
                assert adduser == [
                    "adduser",
                    "--system",
                    "--group",
                    "--uid",
                    "64031",
                    "--no-create-home",
                    "--home",
                    "/nonexistent",
                    "slurmrestd",
                ]
                assert systemctl == ["systemctl", "daemon-reload"]

            case _:
                assert mock_run.call_args[0][0] == ["systemctl", "daemon-reload"]


class TestSnapManager:
    """Unit tests for the `_SnapManager` class."""

    @pytest.fixture(
        params=zip(
            [SackdManager, SlurmctldManager, SlurmdManager, SlurmdbdManager, SlurmrestdManager],
            services,
        ),
        ids=services,
    )
    def mock_manager(self, request, fs: FakeFilesystem) -> tuple[SlurmManager, str]:
        """Request a mocked Slurm service manager and service name."""
        fs.create_file("/var/snap/slurm/common/.env")

        return request.param[0](snap=True), request.param[1]

    def test_install(self, mock_manager, mock_run, mocker: MockerFixture) -> None:
        """Test the `install` method."""
        manager, _ = mock_manager
        mocker.patch("slurm_ops.core.base._SnapManager._apply_overrides")
        mocker.patch("shutil.chown")

        manager.install()
        args = mock_run.call_args_list[0][0][0]
        assert args[:3] == ["snap", "install", "slurm"]
        assert "--classic" in args[3:]

        f_info = Path("/var/snap/slurm/common/var/lib/slurm").stat()
        assert stat.filemode(f_info.st_mode) == "drwxr-xr-x"
        f_info = Path("/var/snap/slurm/common/var/lib/slurm/checkpoint").stat()
        assert stat.filemode(f_info.st_mode) == "drwxr-xr-x"

    def test_version(self, mock_manager, mock_run) -> None:
        """Test the `version` method."""
        manager, _ = mock_manager

        # Test `version` when the Slurm snap is installed.
        mock_run.return_value = CompletedProcess([], returncode=0, stdout=SLURM_SNAP_INFO_ACTIVE)

        assert manager.version() == "23.11.7"
        assert mock_run.call_args[0][0] == ["snap", "info", "slurm"]

        # Test `version` when the Slurm snap is not installed.
        mock_run.return_value = CompletedProcess(
            [], returncode=0, stdout=SLURM_SNAP_INFO_NOT_INSTALLED
        )

        with pytest.raises(SlurmOpsError) as exec_info:
            manager.version()

        assert exec_info.type == SlurmOpsError
        assert exec_info.value.message == (
            "unable to retrieve snap info. ensure slurm is correctly installed"
        )

    def test_is_installed(self, mock_manager, mock_run) -> None:
        """Test the `is_installed` method."""
        manager, _ = mock_manager

        # Test `is_installed` when the Slurm snap is installed.
        mock_run.return_value = CompletedProcess([], returncode=0, stdout=SLURM_SNAP_INFO_ACTIVE)

        assert manager.is_installed() is True

        # Test `is_installed` when the Slurm snap is not installed.
        mock_run.return_value = CompletedProcess(
            [], returncode=0, stdout=SLURM_SNAP_INFO_NOT_INSTALLED
        )

        assert manager.is_installed() is False

    def test_apply_overrides(self, mock_manager, mock_run) -> None:
        """Test the `_apply_overrides` helper function."""
        manager, _ = mock_manager

        manager._ops_manager._apply_overrides()
        assert mock_run.call_args[0][0] == ["snap", "stop", "--disable", "slurm.munged"]
