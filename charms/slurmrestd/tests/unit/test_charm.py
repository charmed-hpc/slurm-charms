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
from unittest.mock import PropertyMock, patch

from charm import SlurmrestdCharm
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness


class TestCharm(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(SlurmrestdCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch(
        "interface_slurmctld.Slurmctld.is_joined",
        new_callable=PropertyMock(return_value=True),
    )
    @patch("slurmrestd_ops.SlurmrestdManager.version", return_value="1.1.1")
    @patch("slurmrestd_ops.SlurmrestdManager.install")
    @patch("slurmrestd_ops.CharmedHPCPackageLifecycleManager.install")
    def test_install_success(self, *_):
        self.harness.charm._stored.slurmctld_available = True
        self.harness.charm.on.install.emit()
        self.assertTrue(self.harness.charm._stored.slurm_installed)
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    def test_update_status_fail(self):
        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Error installing slurmrestd")
        )

    @patch(
        "interface_slurmctld.Slurmctld.is_joined",
        new_callable=PropertyMock(return_value=True),
    )
    @patch("slurmrestd_ops.SlurmrestdManager.check_munged", return_value=True)
    def test_update_status_success(self, *_):
        self.harness.charm._stored.slurm_installed = True

        self.harness.charm.on.update_status.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
