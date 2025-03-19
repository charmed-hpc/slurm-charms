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

"""Test default charm events such as upgrade charm, install, etc."""

from unittest.mock import Mock, PropertyMock, patch

from charm import SlurmrestdCharm
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness
from pyfakefs.fake_filesystem_unittest import TestCase

from charms.hpc_libs.v0.slurm_ops import SlurmOpsError


class TestCharm(TestCase):
    def setUp(self) -> None:
        self.harness = Harness(SlurmrestdCharm)
        self.addCleanup(self.harness.cleanup)
        self.setUpPyfakefs()
        self.harness.begin()

    @patch(
        "interface_slurmctld.Slurmctld.is_joined",
        new_callable=PropertyMock(return_value=True),
    )
    @patch("charms.hpc_libs.v0.slurm_ops._SystemctlServiceManager.active", return_value=True)
    @patch("charms.hpc_libs.v0.slurm_ops._SystemctlServiceManager.enable")
    def test_install_success(self, *_) -> None:
        """Test `InstallEvent` hook success."""
        self.harness.charm._stored.slurmctld_relation_data_available = True
        self.harness.charm._slurmrestd.install = Mock()
        self.harness.charm._slurmrestd.version = Mock(return_value="24.05.2-1")
        self.harness.charm.on.install.emit()

        self.assertTrue(self.harness.charm._stored.slurm_installed)
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    def test_install_fail(self, *_) -> None:
        """Test `InstallEvent` hook failure."""
        self.harness.charm._slurmrestd.install = Mock(
            side_effect=SlurmOpsError("failed to install slurmd")
        )
        self.harness.charm.on.install.emit()

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("failed to install slurmrestd. see logs for further details"),
        )
        self.assertFalse(self.harness.charm._stored.slurm_installed)

    @patch(
        "interface_slurmctld.Slurmctld.is_joined",
        new_callable=PropertyMock(return_value=True),
    )
    @patch("charms.hpc_libs.v0.slurm_ops._SystemctlServiceManager.active", return_value=True)
    def test_update_status_success(self, *_) -> None:
        """Test `UpdateStatusEvent` hook success."""
        self.harness.charm._stored.slurmctld_relation_data_available = True
        self.harness.charm._stored.slurm_installed = True
        self.harness.charm.on.update_status.emit()

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch(
        "interface_slurmctld.Slurmctld.is_joined",
        new_callable=PropertyMock(return_value=True),
    )
    def test_update_status_no_slurmctld_data(self, *_) -> None:
        """Test `UpdateStatusEvent` hook success."""
        self.harness.charm._stored.slurm_installed = True
        self.harness.charm.on.update_status.emit()

        self.assertEqual(
            self.harness.charm.unit.status,
            WaitingStatus("Waiting on relation data from slurmctld."),
        )

    def test_update_status_fail(self):
        """Test `UpdateStatusEvent` hook failure."""
        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("failed to install slurmrestd. see logs for further details"),
        )
