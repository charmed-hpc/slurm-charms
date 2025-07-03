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

"""Manage Slurm's authentication and kiosk service, `sackd`."""

__all__ = ["SackdManager"]

from collections.abc import Iterable

from slurm_ops.core import SLURM_GROUP, SLURM_USER, SlurmManager, marshal_options, parse_options


class SackdManager(SlurmManager):
    """Manage Slurm's authentication and kiosk service, `sackd`."""

    def __init__(self, snap: bool = False) -> None:
        super().__init__("sackd", snap)
        self._env_manager = self._ops_manager.env_manager_for("sackd")

    @property
    def config_server(self) -> list[str] | None:
        """Get the list of controller addresses `sackd` uses to communicate with `slurmctld`."""
        options = parse_options(self._env_manager.get("SACKD_OPTIONS") or "")
        return options.get("--conf-server").split(",") if "--conf-server" in options else None

    @config_server.setter
    def config_server(self, value: Iterable[str]) -> None:
        options = parse_options(self._env_manager.get("SACKD_OPTIONS" or ""))
        options["--conf-server"] = ",".join(value)
        self._env_manager.set({"SACKD_OPTIONS": marshal_options(options)})

    @config_server.deleter
    def config_server(self) -> None:
        options = parse_options(self._env_manager.get("SACKD_OPTIONS" or ""))
        del options["--conf-server"]
        self._env_manager.set({"SACKD_OPTIONS": marshal_options(options)})

    @property
    def user(self) -> str:
        """Get the user that the `sackd` service runs as."""
        return SLURM_USER

    @property
    def group(self) -> str:
        """Get the group that the `sackd` service runs as."""
        return SLURM_GROUP
