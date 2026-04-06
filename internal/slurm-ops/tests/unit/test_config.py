#!/usr/bin/env python3
# Copyright 2025-2026 Canonical Ltd.
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
from constants import FAKE_GROUP, FAKE_GROUP_GID, FAKE_USER, FAKE_USER_UID
from pyfakefs.fake_filesystem import FakeFilesystem
from slurm_ops.core import SlurmConfigManager
from slurmutils import SlurmConfig, SlurmConfigEditor

SLURM_CONF_PATH = Path("/etc/slurm/slurm.conf")
SLURM_CONF_EXAMPLE = """
slurmctldhost=juju-c9fc6f-0(10.152.28.20)
slurmctldhost=juju-c9fc6f-1(10.152.28.100)
clustername=charmed-hpc
authtype=auth/slurm
epilog=/usr/local/slurm/epilog
prolog=/usr/local/slurm/prolog
firstjobid=65536
inactivelimit=120
jobcomptype=jobcomp/filetxt
jobcomploc=/var/log/slurm/jobcomp
killwait=30
maxjobcount=10000
minjobage=3600
plugindir=/usr/local/lib:/usr/local/slurm/lib
returntoservice=0
schedulertype=sched/backfill
slurmctldlogfile=/var/log/slurm/slurmctld.log
slurmdlogfile=/var/log/slurm/slurmd.log
slurmctldport=7002
slurmdport=7003
slurmdspooldir=/var/spool/slurmd.spool
statesavelocation=/var/spool/slurm.state
tmpfs=/tmp
waittime=30
""".lstrip()


@pytest.fixture(scope="function")
def mock_config_manager(fs: FakeFilesystem) -> SlurmConfigManager[SlurmConfigEditor]:
    fs.create_dir(SLURM_CONF_PATH.parent)  # `slurmutils` does not create missing directory paths.

    return SlurmConfigManager(
        SlurmConfigEditor,
        file=SLURM_CONF_PATH,
        mode=0o644,
        user=FAKE_USER,
        group=FAKE_GROUP,
    )


class TestSlurmConfigManager:
    """Test the `SlurmConfigManager` class."""

    def test_name(self, mock_config_manager: SlurmConfigManager) -> None:
        """Test the `name` property."""
        assert mock_config_manager.name == SLURM_CONF_PATH.name

    def test_path(self, mock_config_manager: SlurmConfigManager) -> None:
        """Test the `path` property."""
        assert mock_config_manager.path.as_posix() == SLURM_CONF_PATH.as_posix()

    def test_includes(self, mock_config_manager: SlurmConfigManager, fs: FakeFilesystem) -> None:
        """Test the `includes` property."""
        fs.create_file(mock_config_manager.path.with_suffix(".conf.overrides"))

        includes = mock_config_manager.includes
        assert len(includes) == 1
        assert f"{mock_config_manager.name}.overrides" in includes

        include = includes[f"{mock_config_manager.name}.profiling"]
        assert isinstance(include, SlurmConfigManager)

    def test_snapshots(self, mock_config_manager: SlurmConfigManager, fs: FakeFilesystem) -> None:
        """Test the `snapshots` property."""
        fs.create_file(mock_config_manager.path.with_suffix(".conf.overrides.snapshot"))

        snapshots = mock_config_manager.snapshots
        assert len(snapshots) == 1
        assert f"{mock_config_manager.name}.overrides.snapshot" in snapshots

    def test_exists(self, mock_config_manager: SlurmConfigManager) -> None:
        """Test the `exists` method."""
        assert mock_config_manager.exists() is False
        mock_config_manager.create()
        assert mock_config_manager.exists() is True

    def test_create(self, mock_config_manager: SlurmConfigManager) -> None:
        """Test the `create` method."""
        assert mock_config_manager.exists() is False
        mock_config_manager.create()
        assert mock_config_manager.exists() is True

        file_info = mock_config_manager.path.stat()
        assert stat.filemode(file_info.st_mode) == "-rw-r--r--"
        assert file_info.st_uid == FAKE_USER_UID
        assert file_info.st_gid == FAKE_GROUP_GID

    def test_load(self, mock_config_manager: SlurmConfigManager, fs: FakeFilesystem) -> None:
        """Test the `load` method."""
        fs.create_file(mock_config_manager.path, contents=SLURM_CONF_EXAMPLE)

        assert mock_config_manager.load().dict() == SlurmConfig.from_str(SLURM_CONF_EXAMPLE).dict()

    def test_dump(self, mock_config_manager: SlurmConfigManager) -> None:
        """Test the `dump` method."""
        config = SlurmConfig.from_str(SLURM_CONF_EXAMPLE)

        mock_config_manager.dump(config)
        assert SLURM_CONF_PATH.read_text() == SLURM_CONF_EXAMPLE

        f_info = mock_config_manager.path.stat()
        assert stat.filemode(f_info.st_mode) == "-rw-r--r--"
        assert f_info.st_uid == FAKE_USER_UID
        assert f_info.st_gid == FAKE_GROUP_GID

    def test_edit(self, mock_config_manager: SlurmConfigManager, fs: FakeFilesystem) -> None:
        """Test the `edit` context manager."""
        fs.create_file(mock_config_manager.path, contents=SLURM_CONF_EXAMPLE)

        with mock_config_manager.edit() as config:
            assert config.slurmctld_host == [
                "juju-c9fc6f-0(10.152.28.20)",
                "juju-c9fc6f-1(10.152.28.100)",
            ]
            config.slurmctld_host.pop(1)

        config = mock_config_manager.load()
        assert config.slurmctld_host == ["juju-c9fc6f-0(10.152.28.20)"]

    def test_merge(self, mock_config_manager: SlurmConfigManager, fs: FakeFilesystem) -> None:
        """Test the `merge` method."""
        fs.create_file(SLURM_CONF_PATH.with_suffix(".conf.overrides1"), contents="waittime=9000")
        fs.create_file(SLURM_CONF_PATH.with_suffix(".conf.overrides2"), contents="tmpfs=/scratch")

        mock_config_manager.merge()

        with mock_config_manager.edit() as config:
            assert config.wait_time == 9000
            assert config.tmpfs == "/scratch"

    def test_save(self, mock_config_manager: SlurmConfigManager) -> None:
        """Test the `save` method."""
        mock_config_manager.create()

        mock_config_manager.save()
        assert mock_config_manager.path.with_suffix(".conf.snapshot").exists() is True

        mock_config_manager.path.with_suffix(".conf.snapshot").unlink()
        mock_config_manager.delete()
        mock_config_manager.save()
        assert mock_config_manager.path.with_suffix(".conf.snapshot").exists() is False

    def test_restore(self, mock_config_manager: SlurmConfigManager, fs: FakeFilesystem) -> None:
        """Test the `restore` method."""
        fs.create_file(mock_config_manager.path.with_suffix(".conf.snapshot"))
        assert mock_config_manager.exists() is False

        mock_config_manager.restore()
        assert mock_config_manager.exists() is True

    def test_delete(self, mock_config_manager: SlurmConfigManager) -> None:
        """Test the `delete` method."""
        mock_config_manager.create()
        assert mock_config_manager.exists() is True
        mock_config_manager.delete()
        assert mock_config_manager.exists() is False
