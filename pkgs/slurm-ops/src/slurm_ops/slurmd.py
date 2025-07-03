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

"""Manage Slurm's compute service, `slurmd`."""

__all__ = ["SlurmdManager"]

from collections.abc import Iterable

from slurm_ops.core import SLURMD_GROUP, SLURMD_USER, SlurmManager, marshal_options, parse_options


class SlurmdManager(SlurmManager):
    """Manage Slurm's compute service, `slurmd`."""

    def __init__(self, snap: bool = False) -> None:
        super().__init__("slurmd", snap)
        self._env_manager = self._ops_manager.env_manager_for("slurmd")

    @property
    def config_server(self) -> list[str] | None:
        """Get the list of controller addresses `slurmd` uses to communicate with `slurmctld`."""
        options = parse_options(self._env_manager.get("SLURMD_OPTIONS") or "")
        return options.get("--conf-server").split(",") if "--conf-server" in options else None

    @config_server.setter
    def config_server(self, value: Iterable[str]) -> None:
        options = parse_options(self._env_manager.get("SLURMD_OPTIONS" or ""))
        options["--conf-server"] = ",".join(value)
        self._env_manager.set({"SLURMD_OPTIONS": marshal_options(options)})

    @config_server.deleter
    def config_server(self) -> None:
        options = parse_options(self._env_manager.get("SLURMD_OPTIONS" or ""))
        del options["--conf-server"]
        self._env_manager.set({"SLURMD_OPTIONS": marshal_options(options)})

    @property
    def user(self) -> str:
        """Get the user that the `slurmd` service runs as."""
        return SLURMD_USER

    @property
    def group(self) -> str:
        """Get the group that the `slurmd` service runs as."""
        return SLURMD_GROUP
