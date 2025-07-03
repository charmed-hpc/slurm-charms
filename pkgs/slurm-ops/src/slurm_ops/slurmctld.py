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

from slurm_ops.core import (
    SLURM_GROUP,
    SLURM_USER,
    AcctGatherConfigManager,
    CGroupConfigManager,
    GresConfigManager,
    OCIConfigManager,
    SlurmConfigManager,
    SlurmManager,
)


class SlurmctldManager(SlurmManager):
    """Manage Slurm's controller service, `slurmctld`."""

    def __init__(self, snap: bool = False) -> None:
        super().__init__("slurmctld", snap)

        self.config = SlurmConfigManager(
            self._ops_manager.etc_path / "slurm.conf", user=self.user, group=self.group
        )
        self.acct_gather = AcctGatherConfigManager(
            self._ops_manager.etc_path / "acct_gather.conf", user=self.user, group=self.group
        )
        self.cgroup = CGroupConfigManager(
            self._ops_manager.etc_path / "cgroup.conf", user=self.user, group=self.group
        )
        self.gres = GresConfigManager(
            self._ops_manager.etc_path / "gres.conf", user=self.user, group=self.group
        )
        self.oci = OCIConfigManager(
            self._ops_manager.etc_path / "oci.conf", user=self.user, group=self.group
        )

    @property
    def user(self) -> str:
        """Get the user that the `slurmctld` service runs as."""
        return SLURM_USER

    @property
    def group(self) -> str:
        """Get the group that the `slurmctld` service runs as."""
        return SLURM_GROUP
