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

"""Unit tests for the slurmd operator."""

from unittest.mock import Mock, PropertyMock, patch  # noqa: I001

# Must come before SlurmdCharm import
from module_mocks import apt_pkg_mock, detect_mock  # noqa: F401

from charm import SlurmdCharm
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness
from pyfakefs.fake_filesystem_unittest import TestCase

from utils.rdma import _override_ompi_conf

from hpc_libs.slurm_ops import SlurmOpsError


class TestCharm(TestCase):
    """Unit test slurmd charm."""

    def setUp(self) -> None:
        """Set up unit test."""
        self.harness = Harness(SlurmdCharm)
        self.addCleanup(self.harness.cleanup)
        self.setUpPyfakefs()
        self.harness.begin()

    def test_config_changed_fail(self) -> None:
        """Test config_changed failure behavior."""
        self.harness.set_leader(True)
        self.harness.update_config({"partition-config": "FAILEVAL"})
        self.assertEqual(self.harness.charm._stored.user_supplied_partition_parameters, {})

    @patch("ops.framework.EventBase.defer")
    def test_config_changed_success(self, defer) -> None:
        """Test config_changed success behavior."""
        self.harness.set_leader(True)
        self.harness.update_config(
            {"partition-config": 'DenyAccounts="myacct,youracct" DisableRootJobs="YES"'}
        )
        defer.assert_not_called()

    @patch("utils.rdma._override_ompi_conf")
    @patch("utils.nhc.install")
    @patch("utils.service.override_service")
    @patch("hpc_libs.slurm_ops._SystemctlServiceManager.enable")
    @patch("charms.operator_libs_linux.v0.juju_systemd_notices.SystemdNotices.subscribe")
    @patch("charms.operator_libs_linux.v0.apt.add_package")
    @patch("ops.framework.EventBase.defer")
    def test_install_success(self, defer, apt_mock, *_) -> None:
        """Test install success behavior."""
        self.harness.charm._slurmd.install = Mock()
        self.harness.charm._slurmd.version = Mock(return_value="24.05.2-1")

        # GPU detection test setup
        metapackage = "headless-no-dkms-535-server"
        linux_modules = "linux-modules-535-server"
        detect_mock.system_gpgpu_driver_packages.return_value = {
            "driver-535-server": {"recommended": True, "metapackage": metapackage}
        }
        detect_mock.get_linux_modules_metapackage.return_value = linux_modules

        self.harness.charm.on.install.emit()

        apt_mock.assert_any_call(["rdma-core", "infiniband-diags"])
        apt_mock.assert_any_call([metapackage, linux_modules])
        self.assertTrue(self.harness.charm._stored.slurm_installed)
        defer.assert_not_called()

    @patch("ops.framework.EventBase.defer")
    def test_install_fail(self, defer) -> None:
        """Test install failure behavior."""
        self.harness.charm._slurmd.install = Mock(
            side_effect=SlurmOpsError("failed to install slurmd")
        )
        self.harness.charm.on.install.emit()

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("Install failed. See `juju debug-log` for details"),
        )
        self.assertFalse(self.harness.charm._stored.slurm_installed)
        defer.assert_called()

    def test_override_ompi_conf(self) -> None:
        """Test OpenMPI configuration file override."""
        initial_contents = (
            "# Comment\nmtl = ^ofi\nbtl = ^uct,openib,ofi\npml = ^ucx\nosc = ^ucx,pt2pt\n"
            "# Another comment\nosc = ^ucx,pt2pt\npml = ^ucx\nbtl = ^uct,openib,ofi\nmtl = ^ofi\n"
        )
        expected_contents = (
            "# Comment\nmtl = ^ofi\nbtl = ^openib,ofi\nosc = ^pt2pt\n"
            "# Another comment\nosc = ^pt2pt\nbtl = ^openib,ofi\nmtl = ^ofi\n"
        )
        path = "/etc/openmpi/openmpi-mca-params.conf"
        self.fs.create_file(path, contents=initial_contents)

        _override_ompi_conf()

        with open(path, "r") as f:
            contents = f.read()
        self.assertEqual(contents, expected_contents)

    def test_service_slurmd_start(self) -> None:
        """Test service_slurmd_started event handler."""
        self.harness.charm.on.service_slurmd_started.emit()
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    def test_service_slurmd_stopped(self) -> None:
        """Test service_slurmd_stopped event handler."""
        self.harness.charm.on.service_slurmd_stopped.emit()
        self.assertEqual(self.harness.charm.unit.status, BlockedStatus("slurmd not running"))

    @patch("pynvml.nvmlShutdown")
    @patch("pynvml.nvmlInit")
    @patch("pynvml.nvmlDeviceGetHandleByIndex")
    @patch("pynvml.nvmlDeviceGetMinorNumber")
    @patch("pynvml.nvmlDeviceGetName")
    @patch("pynvml.nvmlDeviceGetCount")
    @patch("utils.machine.get_slurmd_info")
    def test_slurmctld_on_relation_created(self, machine, count, name, number, *_) -> None:
        """Test slurmctld relation create behavior."""
        # Compute node mock data
        node = {
            "NodeName": "node1",
            "CPUs": "16",
            "Boards": "1",
            "SocketsPerBoard": "1",
            "CoresPerSocket": "8",
            "ThreadsPerCore": "2",
            "RealMemory": "31848",
        }
        machine.return_value = node

        # GPU mock data
        count.return_value = 4
        name.side_effect = ["Tesla T4", "Tesla T4", "L40S", "L40S"]
        number.side_effect = [0, 1, 2, 3]

        relation_id = self.harness.add_relation("slurmctld", "slurmd")

        expected = (
            '{"node_parameters": {'
            '"NodeName": "node1", "CPUs": "16", "Boards": "1", '
            '"SocketsPerBoard": "1", "CoresPerSocket": "8", '
            '"ThreadsPerCore": "2", "RealMemory": "31848", '
            '"Gres": ["gpu:tesla_t4:2", "gpu:l40s:2"], "MemSpecLimit": "1024"}, '
            '"new_node": true, '
            '"gres": ['
            '{"Name": "gpu", "Type": "tesla_t4", "File": "/dev/nvidia[0-1]"}, '
            '{"Name": "gpu", "Type": "l40s", "File": "/dev/nvidia[2-3]"}'
            "]}"
        )
        self.assertEqual(self.harness.get_relation_data(relation_id, "slurmd/0")["node"], expected)

    @patch("interface_slurmctld.Slurmctld.is_joined", new_callable=PropertyMock(return_value=True))
    def test_update_status_success(self, *_) -> None:
        """Test `UpdateStateEvent` hook success."""
        self.harness.charm._stored.slurm_installed = True
        self.harness.charm._stored.slurmctld_available = True

        self.harness.charm.unit.status = ActiveStatus()
        self.harness.charm.on.update_status.emit()
        # ActiveStatus is the expected value when _check_status does not
        # modify the current state of the unit and should return True.
        self.assertTrue(self.harness.charm._check_status())
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    def test_update_status_install_fail(self) -> None:
        """Test `UpdateStateEvent` hook failure."""
        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("Install failed. See `juju debug-log` for details"),
        )
