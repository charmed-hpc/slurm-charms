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

"""Test default charm events such as install, etc."""

from unittest.mock import Mock, patch

from charm import SlurmctldCharm
from ops.model import BlockedStatus
from ops.testing import Harness
from pyfakefs.fake_filesystem_unittest import TestCase

from charms.hpc_libs.v0.slurm_ops import SlurmOpsError


class TestCharm(TestCase):

    def setUp(self):
        self.harness = Harness(SlurmctldCharm)
        self.addCleanup(self.harness.cleanup)
        self.setUpPyfakefs()
        self.harness.begin()

    def test_cluster_name(self) -> None:
        """Test that the _cluster_name property works."""
        self.assertEqual(self.harness.charm._cluster_name, "osd-cluster")

    def test_cluster_info(self) -> None:
        """Test the cluster_info property works."""
        self.assertEqual(type(self.harness.charm._cluster_name), str)

    def test_is_slurm_installed(self) -> None:
        """Test that the is_slurm_installed method works."""
        setattr(self.harness.charm._stored, "slurm_installed", True)  # Patch StoredState
        self.assertEqual(self.harness.charm.slurm_installed, True)

    def test_is_slurm_not_installed(self) -> None:
        """Test that the is_slurm_installed method works when slurm is not installed."""
        setattr(self.harness.charm._stored, "slurm_installed", False)  # Patch StoredState
        self.assertEqual(self.harness.charm.slurm_installed, False)

    @patch("charm.SlurmctldCharm._on_write_slurm_conf")
    @patch("ops.framework.EventBase.defer")
    def test_install_success(self, defer, *_) -> None:
        """Test `InstallEvent` hook when slurmctld installation succeeds."""
        self.harness.set_leader(True)
        self.harness.charm._slurmctld.install = Mock()
        self.harness.charm._slurmctld.version = Mock(return_value="24.05.2-1")
        self.harness.charm._slurmctld.jwt = Mock()
        self.harness.charm._slurmctld.jwt.get.return_value = "=X="
        self.harness.charm._slurmctld.munge = Mock()
        self.harness.charm._slurmctld.munge.key.get.return_value = "=X="
        self.harness.charm._slurmctld.exporter = Mock()
        self.harness.charm._slurmctld.service = Mock()

        self.harness.charm.on.install.emit()
        defer.assert_not_called()

    @patch("ops.framework.EventBase.defer")
    def test_install_fail_ha_support(self, defer) -> None:
        """Test `InstallEvent` hook when multiple slurmctld units are deployed.

        Notes:
            The slurmctld charm currently does not support high-availability so this
            unit test validates that we properly handle if multiple slurmctld units
            are deployed.
        """
        self.harness.set_leader(False)
        self.harness.charm.on.install.emit()

        defer.assert_called()
        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("slurmctld high-availability not supported"),
        )

    @patch("ops.framework.EventBase.defer")
    def test_install_fail_slurmctld_package(self, defer) -> None:
        """Test `InstallEvent` hook when slurmctld fails to install."""
        self.harness.set_leader(True)
        self.harness.charm._slurmctld.install = Mock(
            side_effect=SlurmOpsError("failed to install slurmctld")
        )
        self.harness.charm.on.install.emit()

        defer.assert_called()
        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("failed to install slurmctld. see logs for further details"),
        )

    def test_update_status_slurm_not_installed(self) -> None:
        """Test `UpdateStatusEvent` hook when slurmctld is not installed."""
        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("failed to install slurmctld. see logs for further details"),
        )

    def test_get_munge_key(self) -> None:
        """Test that the get_munge_key method works."""
        setattr(self.harness.charm._stored, "munge_key", "=ABC=")  # Patch StoredState
        self.assertEqual(self.harness.charm.get_munge_key(), "=ABC=")

    def test_get_jwt_rsa(self) -> None:
        """Test that the get_jwt_rsa method works."""
        setattr(self.harness.charm._stored, "jwt_rsa", "=ABC=")  # Patch StoredState
        self.assertEqual(self.harness.charm.get_jwt_rsa(), "=ABC=")

    @patch("charm.SlurmctldCharm._check_status", return_value=False)
    def test_on_slurmrestd_available_status_false(self, _) -> None:
        """Test that the on_slurmrestd_available method works when _check_status is False."""
        self.harness.charm._slurmrestd.on.slurmrestd_available.emit()

    @patch("charm.SlurmctldCharm._check_status", return_value=False)
    @patch("interface_slurmrestd.Slurmrestd.set_slurm_config_on_app_relation_data")
    @patch("ops.framework.EventBase.defer")
    def test_on_slurmrestd_available_no_config(self, defer, *_) -> None:
        """Test that the on_slurmrestd_available method works if no slurm config is available."""
        self.harness.set_leader(True)
        self.harness.charm._slurmrestd.on.slurmrestd_available.emit()
        defer.assert_called()

    @patch("charm.SlurmctldCharm._check_status", return_value=True)
    @patch("slurmutils.editors.slurmconfig.load")
    @patch("interface_slurmrestd.Slurmrestd.set_slurm_config_on_app_relation_data")
    def test_on_slurmrestd_available_if_available(self, *_) -> None:
        """Test that the on_slurmrestd_available method works if slurm_config is available.

        Notes:
            This method is testing the _on_slurmrestd_available event handler
            completes successfully.
        """
        self.harness.charm._stored.slurmrestd_available = True
        self.harness.charm._slurmrestd.on.slurmrestd_available.emit()

    def test_on_slurmdbd_available(self) -> None:
        """Test that the on_slurmdbd_method works."""
        self.harness.charm._slurmdbd.on.slurmdbd_available.emit("slurmdbdhost")
        self.assertEqual(self.harness.charm._stored.slurmdbd_host, "slurmdbdhost")

    def test_on_slurmdbd_unavailable(self) -> None:
        """Test that the on_slurmdbd_unavailable method works."""
        self.harness.charm._slurmdbd.on.slurmdbd_unavailable.emit()
        self.assertEqual(self.harness.charm._stored.slurmdbd_host, "")

    @patch("charm.is_container", return_value=True)
    def test_get_user_supplied_parameters(self, *_) -> None:
        """Test that user supplied parameters are parsed correctly."""
        self.harness.add_relation("slurmd", "slurmd")
        self.harness.add_relation("slurmctld-peer", self.harness.charm.app.name)
        self.harness.update_config(
            {"slurm-conf-parameters": "JobAcctGatherFrequency=task=30,network=40"}
        )
        self.assertEqual(
            self.harness.charm._assemble_slurm_conf().job_acct_gather_frequency,
            "task=30,network=40",
        )

    def test_resume_nodes_valid_input(self) -> None:
        """Test that the _resume_nodes method provides a valid scontrol command."""
        self.harness.charm._slurmctld.scontrol = Mock()
        self.harness.charm._resume_nodes(["juju-123456-1", "tester-node", "node-three"])
        args, _ = self.harness.charm._slurmctld.scontrol.call_args
        self.assertEqual(
            args, ("update", "nodename=juju-123456-1,tester-node,node-three", "state=resume")
        )
