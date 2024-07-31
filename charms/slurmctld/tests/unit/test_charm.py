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

import unittest
from unittest.mock import patch

import ops.testing
from charm import SlurmctldCharm
from ops.model import BlockedStatus
from ops.testing import Harness

ops.testing.SIMULATE_CAN_CONNECT = True


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(SlurmctldCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch("slurmctld_ops.SlurmctldManager.hostname", return_val="localhost")
    def test_hostname(self, hostname) -> None:
        """Test that the hostname property works."""
        self.assertEqual(self.harness.charm.hostname, hostname)

    def test_cluster_name(self) -> None:
        """Test that the cluster_name property works."""
        self.assertEqual(self.harness.charm.cluster_name, "osd-cluster")

    def test_cluster_info(self) -> None:
        """Test the cluster_info property works."""
        self.assertEqual(type(self.harness.charm.cluster_name), str)

    def test_is_slurm_installed(self) -> None:
        """Test that the is_slurm_installed method works."""
        setattr(self.harness.charm._stored, "slurm_installed", True)  # Patch StoredState
        self.assertEqual(self.harness.charm.slurm_installed, True)

    def test_is_slurm_not_installed(self) -> None:
        """Test that the is_slurm_installed method works when slurm is not installed."""
        setattr(self.harness.charm._stored, "slurm_installed", False)  # Patch StoredState
        self.assertEqual(self.harness.charm.slurm_installed, False)

    @unittest.expectedFailure
    @patch("slurmctld_ops.SlurmManager.install")
    @patch("slurmctld_ops.SlurmManager.generate_jwt_rsa")
    @patch("charm.SlurmctldCharm.get_jwt_rsa")
    @patch("slurmctld_ops.SlurmManager.configure_jwt_rsa")
    @patch("slurmctld_ops.SlurmManager.get_munge_key")
    def test_install_success(self, *_) -> None:
        """Test that the on_install method works.

        Notes:
            This method is expected to fail due to the 'version' file missing.
        """
        self.harness.charm.on.install.emit()
        self.assertNotEqual(
            self.harness.charm.unit.status, BlockedStatus("Error installing slurmctld")
        )

    # @unittest.expectedFailure
    @patch("slurmctld_ops.SlurmctldManager.install", return_value=False)
    def test_install_fail(self, _) -> None:
        """Test that the on_install method works when slurmctld fails to install.

        Notes:
            This method is expected to fail due to the 'version' file missing.
        """
        self.harness.charm.on.install.emit()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Error installing slurmctld")
        )

    def test_check_status_slurm_not_installed(self) -> None:
        """Test that the check_status method works when slurm is not installed."""
        self.harness.charm._stored.slurm_installed = False
        res = self.harness.charm._check_status()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Error installing slurmctld")
        )
        self.assertEqual(
            res, False, msg="_check_status returned value True instead of expected value False."
        )

    @patch("slurmctld_ops.SlurmctldManager.check_munged", return_value=False)
    def test_check_status_bad_munge(self, _) -> None:
        """Test that the check_status method works when munge encounters an error."""
        setattr(self.harness.charm._stored, "slurm_installed", True)  # Patch StoredState
        res = self.harness.charm._check_status()
        self.assertEqual(
            self.harness.charm.unit.status, BlockedStatus("Error configuring munge key")
        )
        self.assertEqual(
            res, False, msg="_check_status returned value True instead of expected value False."
        )

    def test_get_munge_key(self) -> None:
        """Test that the get_munge_key method works."""
        setattr(self.harness.charm._stored, "munge_key", "=ABC=")  # Patch StoredState
        self.assertEqual(self.harness.charm.get_munge_key(), "=ABC=")

    def test_get_jwt_rsa(self) -> None:
        """Test that the get_jwt_rsa method works."""
        setattr(self.harness.charm._stored, "jwt_rsa", "=ABC=")  # Patch StoredState
        self.assertEqual(self.harness.charm.get_jwt_rsa(), "=ABC=")

    #    @patch(
    #        "slurmctld_ops.SlurmctldManager.charm_maintained_slurm_conf_parameters",
    #        return_value={"SlurmctldParameters": "enable_configless"},
    #    )
    #    @patch("charm.SlurmctldCharm._get_user_supplied_parameters", return_value={})
    #    @patch(
    #        "interface_slurmctld_peer.SlurmctldPeer.get_slurmctld_info",
    #        return_value={"ControlAddr": "192.168.7.1", "ControlMachine": "rats"},
    #    )
    #    @patch("interface_slurmd.Slurmd.get_new_nodes_and_nodes_and_partitions", return_value={})
    #    @patch("charm.SlurmctldCharm._get_slurmdbd_parameters", return_value={})
    #    def test_assemble_slurm_config(self, *_) -> None:
    #        """Test that the assemble_slurm_conf method works."""
    #        self.assertEqual(type(self.harness.charm._assemble_slurm_conf()), dict)

    @patch("charm.SlurmctldCharm._check_status", return_value=False)
    def test_on_slurmrestd_available_status_false(self, _) -> None:
        """Test that the on_slurmrestd_available method works when _check_status is False."""
        self.harness.charm._slurmrestd.on.slurmrestd_available.emit()

    @patch("slurm_conf_editor.slurm_conf_as_string", return_value="")
    @patch("charm.SlurmctldCharm._check_status", return_value=True)
    @patch("charm.SlurmctldCharm._assemble_slurm_conf")
    @patch("ops.framework.EventBase.defer")
    @patch("interface_slurmrestd.Slurmrestd.set_slurm_config_on_app_relation_data")
    def test_on_slurmrestd_available_no_config(self, config, status, defer, *_) -> None:
        """Test that the on_slurmrestd_available method works if no slurm config is available."""
        self.harness.set_leader(True)
        self.harness.charm._slurmrestd.on.slurmrestd_available.emit()
        defer.assert_called()

    @patch("charm.SlurmctldCharm._check_status", return_value=True)
    @patch("charm.SlurmctldCharm._assemble_slurm_conf")
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
