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

"""Unit tests for the Slurm service configuration managers."""

import stat
from pathlib import Path

import pytest
from constants import (
    EXAMPLE_ACCT_GATHER_CONFIG,
    EXAMPLE_CGROUP_CONFIG,
    EXAMPLE_GRES_CONFIG,
    EXAMPLE_OCI_CONFIG,
    EXAMPLE_SLURM_CONFIG,
    EXAMPLE_SLURMDBD_CONFIG,
    FAKE_GROUP,
    FAKE_GROUP_GID,
    FAKE_USER,
    FAKE_USER_UID,
)
from pyfakefs.fake_filesystem import FakeFilesystem
from slurm_ops.core import SlurmConfigManager, SlurmManager
from slurmutils import (
    AcctGatherConfigEditor,
    CGroupConfigEditor,
    DownNodes,
    GresConfigEditor,
    Node,
    OCIConfigEditor,
    SlurmConfigEditor,
    SlurmdbdConfigEditor,
)


class MockManager(SlurmManager):
    """Mock manager for testing configuration managers."""

    def __init__(self) -> None:
        super().__init__("mock", snap=False)

        self.acct_gather = SlurmConfigManager(
            AcctGatherConfigEditor,
            file=self._ops_manager.etc_path / "acct_gather.conf",
            mode=0o600,
            user=self.user,
            group=self.group,
        )
        self.cgroup = SlurmConfigManager(
            CGroupConfigEditor,
            file=self._ops_manager.etc_path / "cgroup.conf",
            mode=0o644,
            user=self.user,
            group=self.group,
        )
        self.gres = SlurmConfigManager(
            GresConfigEditor,
            file=self._ops_manager.etc_path / "gres.conf",
            mode=0o644,
            user=self.user,
            group=self.group,
        )
        self.oci = SlurmConfigManager(
            OCIConfigEditor,
            file=self._ops_manager.etc_path / "oci.conf",
            mode=0o644,
            user=self.user,
            group=self.group,
        )
        self.slurm = SlurmConfigManager(
            SlurmConfigEditor,
            file=self._ops_manager.etc_path / "slurm.conf",
            mode=0o644,
            user=self.user,
            group=self.group,
        )
        self.slurmdbd = SlurmConfigManager(
            SlurmdbdConfigEditor,
            file=self._ops_manager.etc_path / "slurmdbd.conf",
            mode=0o600,
            user=self.user,
            group=self.group,
        )

    @property
    def user(self) -> str:
        return FAKE_USER

    @property
    def group(self) -> str:
        return FAKE_GROUP


class TestConfigManagers:
    """Unit tests for Slurm service configuration managers."""

    @pytest.fixture
    def mock_manager(self, fs: FakeFilesystem) -> MockManager:
        """Request a mocked manager with mocked configuration managers."""
        fs.create_file("/etc/slurm/acct_gather.conf", contents=EXAMPLE_ACCT_GATHER_CONFIG)
        fs.create_file("/etc/slurm/cgroup.conf", contents=EXAMPLE_CGROUP_CONFIG)
        fs.create_file("/etc/slurm/gres.conf", contents=EXAMPLE_GRES_CONFIG)
        fs.create_file("/etc/slurm/oci.conf", contents=EXAMPLE_OCI_CONFIG)
        fs.create_file("/etc/slurm/slurm.conf", contents=EXAMPLE_SLURM_CONFIG)
        fs.create_file("/etc/slurm/slurmdbd.conf", contents=EXAMPLE_SLURMDBD_CONFIG)

        return MockManager()

    # Test configuration managers.

    def test_acct_gather_config_manager(self, mock_manager) -> None:
        """Test the `acct_gather.conf` configuration manager."""
        with mock_manager.acct_gather.edit() as config:
            assert config.energy_ipmi_frequency == 1
            assert config.energy_ipmi_calc_adjustment is True
            assert config.sysfs_interfaces == ["enp0s1"]

            config.energy_ipmi_frequency = 2
            config.energy_ipmi_calc_adjustment = False
            config.sysfs_interfaces = ["enp0s2"]

        # Exit the context to save changes to the acct_gather.conf file.
        config = mock_manager.acct_gather.load()
        assert config.energy_ipmi_frequency == 2
        assert config.energy_ipmi_calc_adjustment is False
        assert config.sysfs_interfaces == ["enp0s2"]

        # Ensure that permissions on the acct_gather.conf are correct.
        f_info = Path("/etc/slurm/acct_gather.conf").stat()
        assert stat.filemode(f_info.st_mode) == "-rw-------"
        assert f_info.st_uid == FAKE_USER_UID
        assert f_info.st_gid == FAKE_GROUP_GID

        # Create a snapshot of the `acct_gather.conf` file.
        mock_manager.acct_gather.save()
        snapshot = mock_manager.acct_gather.snapshots["acct_gather.conf.snapshot"]
        config = snapshot.load()

        assert snapshot.path.exists()
        assert config.energy_ipmi_frequency == 2
        assert config.energy_ipmi_calc_adjustment is False
        assert config.sysfs_interfaces == ["enp0s2"]

        # Restore the `acct_gather.conf` snapshot.
        # Modify the snapshot so we can verify that `acct_gather.conf` is the restored snapshot.
        with snapshot.edit() as config:
            config.sysfs_interfaces += ["wlp1s0"]

        mock_manager.acct_gather.restore()
        config = mock_manager.acct_gather.load()
        assert config.sysfs_interfaces == ["enp0s2", "wlp1s0"]

    def test_cgroup_config_manager(self, mock_manager) -> None:
        """Test the `cgroup.conf` configuration manager."""
        with mock_manager.cgroup.edit() as config:
            assert config.constrain_cores is True
            assert config.constrain_devices is True

            config.constrain_cores = False
            config.constrain_devices = False
            config.constrain_ram_space = False
            config.constrain_swap_space = False

        # Exit the context to save changes to the cgroup.conf file.
        config = mock_manager.cgroup.load()
        assert config.constrain_cores is False
        assert config.constrain_devices is False
        assert config.constrain_ram_space is False
        assert config.constrain_swap_space is False

        # Ensure that permissions on the cgroup.conf file are correct.
        f_info = Path("/etc/slurm/cgroup.conf").stat()
        assert stat.filemode(f_info.st_mode) == "-rw-r--r--"
        assert f_info.st_uid == FAKE_USER_UID
        assert f_info.st_gid == FAKE_GROUP_GID

        # Create a snapshot of the `cgroup.conf` file.
        mock_manager.cgroup.save()
        snapshot = mock_manager.cgroup.snapshots["cgroup.conf.snapshot"]
        config = snapshot.load()

        assert snapshot.path.exists()
        assert config.constrain_cores is False
        assert config.constrain_devices is False
        assert config.constrain_ram_space is False
        assert config.constrain_swap_space is False

        # Restore the `cgroup.conf` snapshot.
        # Modify the snapshot so we can verify that `cgroup.conf` is the restored snapshot.
        with snapshot.edit() as config:
            config.constrain_swap_space = True

        mock_manager.cgroup.restore()
        config = mock_manager.cgroup.load()
        assert config.constrain_swap_space is True

    def test_gres_config_manager(self, mock_manager) -> None:
        """Test the `gres.conf` configuration manager."""
        with mock_manager.gres.edit() as config:
            assert config.auto_detect == "nvml"
            assert config.gres.dict() == {
                "gpu": [
                    {
                        "name": "gpu",
                        "type": "gp100",
                        "file": "/dev/nvidia0",
                        "cores": [0, 1],
                    },
                    {
                        "name": "gpu",
                        "type": "gp100",
                        "file": "/dev/nvidia1",
                        "cores": [0, 1],
                    },
                    {
                        "name": "gpu",
                        "type": "p6000",
                        "file": "/dev/nvidia2",
                        "cores": [2, 3],
                    },
                    {
                        "name": "gpu",
                        "type": "p6000",
                        "file": "/dev/nvidia3",
                        "cores": [2, 3],
                    },
                    {
                        "name": "gpu",
                        "nodename": "juju-c9c6f-[1-10]",
                        "type": "rtx",
                        "file": "/dev/nvidia[0-3]",
                        "count": "8G",
                    },
                ],
                "mps": [
                    {"name": "mps", "count": 200, "file": "/dev/nvidia0"},
                    {"name": "mps", "count": 200, "file": "/dev/nvidia1"},
                    {"name": "mps", "count": 100, "file": "/dev/nvidia2"},
                    {"name": "mps", "count": 100, "file": "/dev/nvidia3"},
                ],
                "bandwidth": [
                    {
                        "name": "bandwidth",
                        "type": "lustre",
                        "count": "4G",
                        "flags": ["countonly"],
                    },
                ],
            }

            del config.auto_detect

        # Exit the context to save changes to the gres.conf file.
        config = mock_manager.gres.load()
        assert config.auto_detect is None

        # Ensure that permissions on the gres.conf file are correct.
        f_info = Path("/etc/slurm/gres.conf").stat()
        assert stat.filemode(f_info.st_mode) == "-rw-r--r--"
        assert f_info.st_uid == FAKE_USER_UID
        assert f_info.st_gid == FAKE_GROUP_GID

        # Create a snapshot of the `gres.conf` file.
        mock_manager.gres.save()
        snapshot = mock_manager.gres.snapshots["gres.conf.snapshot"]
        config = snapshot.load()

        assert snapshot.path.exists()
        assert config.auto_detect is None

        # Restore the `gres.conf` snapshot.
        # Modify the snapshot so we can verify that `gres.conf` is the restored snapshot.
        with snapshot.edit() as config:
            config.auto_detect = "rsmi"

        mock_manager.gres.restore()
        config = mock_manager.gres.load()
        assert config.auto_detect == "rsmi"

    def test_oci_config_manager(self, mock_manager) -> None:
        """Test the `oci.conf` configuration manager."""
        with mock_manager.oci.edit() as config:
            assert config.ignore_file_config_json is True
            assert config.run_time_run == "singularity exec --userns %r %@"

            config.ignore_file_config_json = False
            config.run_time_run = "apptainer exec --userns %r %@"

        config = mock_manager.oci.load()
        assert config.ignore_file_config_json is False
        assert config.run_time_run == "apptainer exec --userns %r %@"

        # Ensure that permissions on the `oci.conf` configuration file are correct.
        f_info = Path("/etc/slurm/oci.conf").stat()
        assert stat.filemode(f_info.st_mode) == "-rw-r--r--"
        assert f_info.st_uid == FAKE_USER_UID
        assert f_info.st_gid == FAKE_GROUP_GID

        # Create a snapshot of the `oci.conf` file.
        mock_manager.oci.save()
        snapshot = mock_manager.oci.snapshots["oci.conf.snapshot"]
        config = snapshot.load()

        assert snapshot.path.exists()
        assert config.ignore_file_config_json is False
        assert config.run_time_run == "apptainer exec --userns %r %@"

        # Restore the `oci.conf` snapshot.
        # Modify the snapshot so we can verify that `oci.conf` is the restored snapshot.
        with snapshot.edit() as config:
            config.ignore_file_config_json = True

        mock_manager.oci.restore()
        config = mock_manager.oci.load()
        assert config.ignore_file_config_json is True

    def test_slurm_config_manager(self, mock_manager) -> None:
        """Test the `slurm.conf` configuration manager."""
        with mock_manager.slurm.edit() as config:
            assert config.slurmd_log_file == "/var/log/slurm/slurmd.log"
            assert config.nodes["juju-c9fc6f-2"].node_addr == "10.152.28.48"
            assert config.down_nodes[0].state == "down"

            config.slurmctld_port = 8081
            config.nodes["juju-c9fc6f-2"].cpus = 10
            config.nodes["juju-c9fc6f-20"] = Node(nodename="juju-c9fc6f-20", cpus=1)
            config.down_nodes.append(
                DownNodes(downnodes=["juju-c9fc6f-3"], state="down", reason="New nodes")
            )
            del config.return_to_service

        # Exit the context to save changes to the slurm.conf file.
        config = mock_manager.slurm.load()
        assert config.slurmctld_port == 8081
        assert config.return_to_service is None

        content = str(config).splitlines()
        assert (
            "nodename=juju-c9fc6f-2 nodeaddr=10.152.28.48 cpus=10 realmemory=1000 tmpdisk=10000"
            in content
        )
        assert "nodename=juju-c9fc6f-20 cpus=1" in content
        assert 'downnodes=juju-c9fc6f-3 state=down reason="New nodes"' in content

        # Ensure that permissions on the slurm.conf file are correct.
        f_info = Path("/etc/slurm/slurm.conf").stat()
        assert stat.filemode(f_info.st_mode) == "-rw-r--r--"
        assert f_info.st_uid == FAKE_USER_UID
        assert f_info.st_gid == FAKE_GROUP_GID

        # Create a fake include file to ensure that it is picked up by the `includes` property.
        Path("/etc/slurm/slurm.conf.overrides").touch(mode=0o611)
        assert "slurm.conf.overrides" in mock_manager.slurm.includes
        assert mock_manager.slurm.includes["slurm.conf.overrides"].path.exists()

    def test_slurmdbd_config_manager(self, mock_manager) -> None:
        """Test the `slurmdbd.conf` configuration manager."""
        with mock_manager.slurmdbd.edit() as config:
            assert config.auth_type == "auth/slurm"
            assert config.debug_level == "info"

            config.storage_pass = "newpass"
            config.log_file = "/var/log/slurm/slurmdbd.log"
            del config.slurm_user

        # Exit the context to save changes to the slurmdbd.conf file.
        config = mock_manager.slurmdbd.load()
        assert config.storage_pass == "newpass"
        assert config.log_file == "/var/log/slurm/slurmdbd.log"
        assert config.slurm_user is None

        # Ensure that permissions on the slurmdbd.conf file are correct.
        f_info = Path("/etc/slurm/slurmdbd.conf").stat()
        assert stat.filemode(f_info.st_mode) == "-rw-------"
        assert f_info.st_uid == FAKE_USER_UID
        assert f_info.st_gid == FAKE_GROUP_GID

        # Create an include that holds custom configuration for `slurmdbd`.
        include = mock_manager.slurmdbd.includes["slurmdbd.conf.overrides"]
        assert include.path.exists() is False
        assert include.path.is_absolute()
        assert include.path.as_posix() == "/etc/slurm/slurmdbd.conf.overrides"

        # Set a custom configuration in the include file.
        with include.edit() as overrides:
            overrides.debug_level = "debug"

        # Check that the include file now exists.
        assert include.path.exists() is True

        # Check the debug level of the main `slurmdbd.conf` file before merging the includes.
        config = mock_manager.slurmdbd.load()
        assert config.debug_level == "info"
        # Now merge the main `slurmdbd.conf` together with `slurmdbd.conf.overrides`.
        # `slurmdbd.conf` does not have an 'include'  directive like `slurm.conf`.
        mock_manager.slurmdbd.merge()
        config = mock_manager.slurmdbd.load()
        assert config.debug_level == "debug"

        # Check a snapshot of both the `slurmdbd.conf` and `slurmdbd.conf.overrides` files.
        mock_manager.slurmdbd.save()
        assert "slurmdbd.conf.snapshot" in mock_manager.slurmdbd.snapshots
        assert "slurmdbd.conf.overrides.snapshot" in mock_manager.slurmdbd.snapshots

        # Restore the `slurmdbd.conf` and `slurmdbd.conf.overrides` snapshots.
        # Modify the `slurmdbd.conf.overrides` to ensure include snapshots are also restored.
        with mock_manager.slurmdbd.snapshots["slurmdbd.conf.overrides.snapshot"].edit() as config:
            config.debug_level = "debug5"

        mock_manager.slurmdbd.restore()
        config = mock_manager.slurmdbd.includes["slurmdbd.conf.overrides"].load()
        assert config.debug_level == "debug5"
