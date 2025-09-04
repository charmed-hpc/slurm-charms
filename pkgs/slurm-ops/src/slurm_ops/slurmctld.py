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

"""Manage Slurm's controller service, `slurmctld`."""

__all__ = ["SlurmctldManager"]

import json
from slurmutils import (
    AcctGatherConfigEditor,
    CGroupConfigEditor,
    GresConfigEditor,
    OCIConfigEditor,
    SlurmConfigEditor,
)

from slurm_ops import scontrol
from slurm_ops.core import SLURM_GROUP, SLURM_USER, SlurmConfigManager, SlurmManager


class SlurmctldManager(SlurmManager):
    """Manage Slurm's controller service, `slurmctld`."""

    def __init__(self, snap: bool = False) -> None:
        super().__init__("slurmctld", snap)

        self.config = SlurmConfigManager(
            SlurmConfigEditor,
            file=self._ops_manager.etc_path / "slurm.conf",
            mode=0o644,
            user=self.user,
            group=self.group,
        )
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

    def get_default_partition(self) -> str:
        """Get the name of the default partition.

        Returns:
            Name of the default partition. An empty string is returned if there is
            no configured default partition.
        """
        for include in self.config.includes.values():
            config = include.load()
            for partition in config.partitions.values():
                if partition.default:
                    return partition.partition_name

        return ""

    def get_controller_status(self) -> str:
        """Return the status of the current controller instance."""
        # Example snippet of ping output:
        #   "pings": [
        #     {
        #       "hostname": "juju-829e74-84",
        #       "pinged": "DOWN",
        #       "latency": 123,
        #       "mode": "primary"
        #     },
        #     {
        #       "hostname": "juju-829e74-85",
        #       "pinged": "UP",
        #       "latency": 456,
        #       "mode": "backup1"
        #     },
        #     {
        #       "hostname": "juju-829e74-86",
        #       "pinged": "UP",
        #       "latency": 789,
        #       "mode": "backup2"
        #     }
        #   ],
        stdout, _ = scontrol("ping", "--json")
        ping_output = json.loads(stdout)

        for ping in ping_output["pings"]:
            if ping["hostname"] == self.hostname:
                return f"{ping['mode']} - {ping['pinged']}"

        return ""

    @property
    def user(self) -> str:
        """Get the user that the `slurmctld` service runs as."""
        return SLURM_USER

    @property
    def group(self) -> str:
        """Get the group that the `slurmctld` service runs as."""
        return SLURM_GROUP
