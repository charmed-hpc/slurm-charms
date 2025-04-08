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

from unittest.mock import Mock, PropertyMock, patch

from charm import SlurmctldCharm
from hpc_libs.slurm_ops import SlurmOpsError
from interface_slurmctld_peer import SlurmctldPeerError
from ops.model import BlockedStatus
from ops.testing import Harness
from pyfakefs.fake_filesystem_unittest import TestCase


class TestCharm(TestCase):
    def setUp(self):
        self.harness = Harness(SlurmctldCharm)
        self.addCleanup(self.harness.cleanup)
        self.setUpPyfakefs()
        self.harness.begin()

    def test_slurmctld_peer_exception_when_setting_cluster_name_fails_due_to_no_relation(
        self,
    ) -> None:
        """Test that the the slurmctld-peer exception is raised when setting cluster_name fails due to non-existent relation.

        The slurmctld-peer relation isn't available until after the install hook event completes.
        This test checks that the appropriate error is raised, when the cluster_name is set, but no peer-relation is available.
        """
        self.harness.set_leader(True)
        with self.assertRaises(SlurmctldPeerError):
            self.harness.charm._slurmctld_peer.cluster_name = "thisshouldfail"

    @patch("charm.SlurmctldCharm._on_install")
    @patch("ops.framework.EventBase.defer")
    def test_start_hook_defers_if_setting_cluster_name_fails(self, defer, *_) -> None:
        """Test that the start event defers if setting cluster_name fails when no relation exists.

        This test checks that event.defer() is called, and charm unit status is Blocked
        when the cluster_name is set, but no peer-relation is available.

        The slurmctld-peer relation isn't available until after the install hook event completes,
        so in theory, the peer-relation *should* always be available by the start hook event executes
        and thus, this case *should* never happen. This code tests that the appropriate action is taken
        in the unusual case that the peer-relation isn't made by the time the start hook executes.
        """
        self.harness.set_leader(True)

        # Do not add the peer-relation
        # self.harness.add_relation("slurmctld-peer", self.harness.charm.app.name)

        self.harness.update_config({"cluster-name": "osd-cluster"})
        self.harness.charm.on.start.emit()

        defer.assert_called()

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("`slurmctld-peer` relation not available yet, cannot set cluster_name."),
        )

    @patch("charm.SlurmctldCharm._on_install")
    @patch("ops.framework.EventBase.defer")
    def test_slurmctld_status_in_start_hook_as_non_leader(self, defer, *_) -> None:
        """Test that the correct status is set if you enter the start hook as a non-leader."""
        self.harness.set_leader(False)
        self.harness.add_relation("slurmctld-peer", self.harness.charm.app.name)

        self.harness.charm.on.start.emit()

        defer.assert_called()

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("High availability of slurmctld is not supported at this time."),
        )

    @patch("charm.SlurmctldCharm._on_write_slurm_conf")
    @patch("charm.SlurmctldCharm._on_install")
    def test_cluster_name(self, *_) -> None:
        """Test that the _cluster_name property works."""
        self.harness.set_leader(True)
        self.harness.add_relation("slurmctld-peer", self.harness.charm.app.name)
        self.harness.update_config({"cluster-name": "osd-cluster"})
        self.harness.charm.on.start.emit()
        self.assertEqual(self.harness.charm.cluster_name, "osd-cluster")

    @patch("charm.SlurmctldCharm._on_write_slurm_conf")
    @patch("charm.SlurmctldCharm._on_install")
    def test_cluster_name_type(self, *_) -> None:
        """Test the cluster_name is indeed a string."""
        self.harness.set_leader(True)
        self.harness.add_relation("slurmctld-peer", self.harness.charm.app.name)
        self.harness.update_config({"cluster-name": "osd-cluster"})
        self.harness.charm.on.start.emit()
        self.assertEqual(type(self.harness.charm.cluster_name), str)

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
        self.harness.charm._slurmctld.key = Mock()
        self.harness.charm._slurmctld.key.get.return_value = "=X="
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
        self.harness.charm.on.update_status.emit()

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

    def test_get_auth_key(self) -> None:
        """Test that the get_auth_key method works."""
        setattr(self.harness.charm._stored, "auth_key", "=ABC=")  # Patch StoredState
        self.assertEqual(self.harness.charm.get_auth_key(), "=ABC=")

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

    @patch(
        "hpc_libs.slurm_ops.SlurmctldManager.hostname",
        new_callable=PropertyMock(return_value="test_hostname"),
    )
    def test_sackd_on_relation_created(self, *_) -> None:
        """Test that sackd relation is created successfully."""
        self.harness.set_leader(True)
        # Patch StoredState
        setattr(self.harness.charm._stored, "slurm_installed", True)
        setattr(self.harness.charm._stored, "auth_key", "=ABC=")

        relation_id = self.harness.add_relation("login-node", "sackd")
        self.assertEqual(
            self.harness.get_relation_data(relation_id, "slurmctld")["cluster_info"],
            '{"auth_key": "=ABC=", "slurmctld_host": "test_hostname"}',
        )

    @patch("ops.framework.EventBase.defer")
    def test_sackd_fail_on_relation_created(self, defer) -> None:
        """Test sackd relation when slurm is not installed."""
        setattr(self.harness.charm._stored, "slurm_installed", False)  # Patch StoredState
        self.harness.add_relation("login-node", "sackd")
        defer.asset_called()

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
