#!/usr/bin/env python3
# Copyright 2025-2026 Canonical Ltd.
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

"""Unit tests for the `slurmctld` charmed operator."""

import textwrap
from pathlib import Path
from unittest.mock import call

import pytest
from constants import HA_MOUNT_INTEGRATION_NAME, HA_MOUNT_LOCATION
from ops import testing
from pyfakefs.fake_filesystem import FakeFilesystem
from pytest_mock import MockerFixture

MOUNT_INTEGRATION_INTERFACE = "mount_info"


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSlurmctldHA:
    """Unit tests for high availability functionality in the `slurmctld` charmed operator."""

    def test_ha_migration_empty_filesystem(
        self, mocker: MockerFixture, mock_charm, fs: FakeFilesystem, leader
    ) -> None:
        """Test high availability data migration logic to an empty shared filesystem."""
        # The HA migration process uses `rsync` via `subprocess.run`. This is not compatible with
        # pyfakefs as the spawned process is unaware of the fake filesystem.
        # Patch `subprocess.run` to avoid execution of `rsync` and verify invocation instead.
        mock_subprocess_run = mocker.patch("subprocess.run")

        # Set up an empty mount location and populate source directories with sample files
        etc_slurm = Path("/etc/slurm")
        statesave = Path("/var/lib/slurm/checkpoint")

        slurm_conf_init = textwrap.dedent(f"""\
            slurmctldhost=hostname
            statesavelocation={statesave}
        """)
        fs.create_file(etc_slurm / "slurm.conf", contents=slurm_conf_init)

        # Simulate HA filesystem being mounted
        rel = testing.SubordinateRelation(
            endpoint=HA_MOUNT_INTEGRATION_NAME,
            interface=MOUNT_INTEGRATION_INTERFACE,
            remote_unit_data={"mounted": "true"},
        )
        mock_charm.run(
            mock_charm.on.relation_changed(rel), testing.State(relations={rel}, leader=leader)
        )

        # Verify migration results.
        ha_fs_prefix = Path(HA_MOUNT_LOCATION)
        ha_etc_slurm = ha_fs_prefix / "etc" / "slurm"
        ha_statesave = ha_fs_prefix / statesave.name
        assert etc_slurm.resolve() == ha_etc_slurm

        rsync_call = call(
            ["/usr/bin/rsync", "--archive", "--delete", str(statesave), str(ha_fs_prefix)],
            input=None,
            capture_output=True,
            text=True,
            check=True,
        )

        if leader:
            slurm_conf_final = textwrap.dedent(f"""\
                slurmctldhost=hostname
                statesavelocation={ha_statesave}
            """)

            assert (ha_etc_slurm / "slurm.conf").read_text() == slurm_conf_final
            assert rsync_call in mock_subprocess_run.mock_calls
        else:
            # Only leader migrates files
            assert not ha_etc_slurm.exists()
            assert rsync_call not in mock_subprocess_run.mock_calls

    def test_ha_migration_nonempty_filesystem(
        self, mock_charm, mocker: MockerFixture, fs: FakeFilesystem, leader
    ) -> None:
        """Test high availability data migration logic to a filesystem already containing data."""
        mock_subprocess_run = mocker.patch("subprocess.run")

        # Populate source and target directories with different sample files
        etc_slurm = Path("/etc/slurm")
        statesave = Path("/var/lib/slurm/checkpoint")
        ha_fs_prefix = Path(HA_MOUNT_LOCATION)
        ha_etc_slurm = ha_fs_prefix / "etc" / "slurm"
        ha_statesave = ha_fs_prefix / statesave.name

        slurm_conf_source = textwrap.dedent(f"""\
            slurmctldhost=hostname0
            statesavelocation={statesave}
        """)
        slurm_conf_target = textwrap.dedent(f"""\
            slurmctldhost=hostname1
            statesavelocation={ha_statesave}
        """)
        fs.create_file(etc_slurm / "slurm.conf", contents=slurm_conf_source)
        fs.create_file(ha_etc_slurm / "slurm.conf", contents=slurm_conf_target)
        fs.create_file(ha_statesave / "myfile", contents="some data")

        # Simulate HA filesystem being mounted
        rel = testing.SubordinateRelation(
            endpoint=HA_MOUNT_INTEGRATION_NAME,
            interface=MOUNT_INTEGRATION_INTERFACE,
            remote_unit_data={"mounted": "true"},
        )
        mock_charm.run(
            mock_charm.on.relation_changed(rel), testing.State(relations={rel}, leader=leader)
        )

        assert etc_slurm.resolve() == ha_etc_slurm
        # Assert no file migration occurred as target is non-empty
        assert (ha_etc_slurm / "slurm.conf").read_text() == slurm_conf_target
        for call_args, _ in mock_subprocess_run.call_args_list:
            assert call_args[0][0] != "/usr/bin/rsync", "rsync was called: migration was attempted"
