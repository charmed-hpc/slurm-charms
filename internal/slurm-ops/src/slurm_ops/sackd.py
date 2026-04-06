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

from slurm_ops.core import SLURM_GROUP, SLURM_USER, SlurmManager


class SackdManager(SlurmManager):
    """Manage Slurm's authentication and kiosk service, `sackd`."""

    def __init__(self, snap: bool = False) -> None:
        super().__init__("sackd", snap)

    @property
    def conf_server(self) -> list[str]:
        """Get the list of controller addresses `sackd` uses to communicate with `slurmctld`."""
        options = self._load_options()
        return list(filter(None, options.get("--conf-server", "").split(",")))

    @conf_server.setter
    def conf_server(self, value: Iterable[str]) -> None:
        with self._edit_options() as options:
            options["--conf-server"] = ",".join(value)

    @conf_server.deleter
    def conf_server(self) -> None:
        with self._edit_options() as options:
            options.pop("--conf-server", None)

    @property
    def user(self) -> str:
        """Get the user that the `sackd` service runs as."""
        return SLURM_USER

    @property
    def group(self) -> str:
        """Get the group that the `sackd` service runs as."""
        return SLURM_GROUP
