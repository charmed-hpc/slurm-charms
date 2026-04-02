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

"""Manage Slurm's database service, `slurmdbd`."""

__all__ = ["SlurmdbdManager"]

from os import PathLike

from slurmutils import SlurmdbdConfigEditor

from slurm_ops.core import SLURM_GROUP, SLURM_USER, SlurmConfigManager, SlurmManager


class SlurmdbdManager(SlurmManager):
    """Manage Slurm's database service, `slurmdbd`."""

    def __init__(self, snap: bool = False) -> None:
        super().__init__("slurmdbd", snap)

    @property
    def config(self) -> SlurmConfigManager:
        """Get the configuration manager for the `slurmdbd.conf` file."""
        return SlurmConfigManager(
            SlurmdbdConfigEditor,
            file=self._ops_manager.etc_path / "slurmdbd.conf",
            mode=0o600,
            user=self.user,
            group=self.group,
        )

    @property
    def overrides(self) -> SlurmConfigManager:
        """Get the configuration manager for the `slurmdbd.conf.overrides` file."""
        return self.config.includes["slurmdbd.conf.overrides"]

    @property
    def storage(self) -> SlurmConfigManager:
        """Get the configuration manager for the `slurmdbd.conf.storage` file."""
        return self.config.includes["slurmdbd.conf.storage"]

    @property
    def mysql_unix_port(self) -> str | None:
        """Get the URI of the unix socket the `slurmd` service uses to communication with MySQL."""
        return self._env_manager.get("MYSQL_UNIX_PORT")

    @mysql_unix_port.setter
    def mysql_unix_port(self, value: str | PathLike) -> None:
        self._env_manager.set({"MYSQL_UNIX_PORT": value})

    @mysql_unix_port.deleter
    def mysql_unix_port(self) -> None:
        self._env_manager.unset("MYSQL_UNIX_PORT")

    @property
    def user(self) -> str:
        """Get the user that the `slurmdbd` service runs as."""
        return SLURM_USER

    @property
    def group(self) -> str:
        """Get the group that the `slurmdbd` service runs as."""
        return SLURM_GROUP

    def reconfigure(self) -> None:
        """Reconfigure the `slurmdbd` service running on the machine.

        Raises:
            SlurmOpsError: Raised if a failure occurs when reconfiguring the `slurmdbd` service.
        """
        self.config.merge()
        super().reconfigure()
