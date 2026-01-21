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

from slurmutils import Node

from slurm_ops.core import SLURMD_GROUP, SLURMD_USER, SlurmManager


class SlurmdManager(SlurmManager):
    """Manage Slurm's compute service, `slurmd`."""

    def __init__(self, snap: bool = False) -> None:
        super().__init__("slurmd", snap)

    @property
    def conf(self) -> Node:
        """Get the current node configuration."""
        options = self._load_options()
        return Node.from_str(options.get("--conf", ""))

    @conf.setter
    def conf(self, value: Node) -> None:
        with self._edit_options() as options:
            options["--conf"] = str(value)

    @conf.deleter
    def conf(self) -> None:
        with self._edit_options() as options:
            options.pop("--conf", None)

    @property
    def conf_server(self) -> list[str]:
        """Get the list of controller addresses `slurmd` uses to communicate with `slurmctld`."""
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
    def dynamic(self) -> bool:
        """Determine if this is a dynamic node."""
        options = self._load_options()
        return options.get("-Z", False)

    @dynamic.setter
    def dynamic(self, value: bool) -> None:
        with self._edit_options() as options:
            options["-Z"] = value

    @property
    def name(self) -> str:
        """Get the name that the compute node is registered under in Slurm."""
        options = self._load_options()
        return options.get("-N", "")

    @name.setter
    def name(self, value: str) -> None:
        with self._edit_options() as options:
            options["-N"] = value

    @property
    def user(self) -> str:
        """Get the user that the `slurmd` service runs as."""
        return SLURMD_USER

    @property
    def group(self) -> str:
        """Get the group that the `slurmd` service runs as."""
        return SLURMD_GROUP
