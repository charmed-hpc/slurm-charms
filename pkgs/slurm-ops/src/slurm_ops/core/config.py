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

"""Configuration managers for Slurm operations managers."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from os import PathLike
from pathlib import Path
from typing import Any

from slurmutils import (
    AcctGatherConfigEditor,
    BaseEditor,
    CGroupConfigEditor,
    GresConfigEditor,
    OCIConfigEditor,
    SlurmConfigEditor,
    SlurmdbdConfigEditor,
)


class ConfigManager(ABC):
    """Base class for composing Slurm configuration managers.

    Args:
        file: Path to the managed configuration file.
        mode: File access mode to assign the configuration file.
        user: System user that owns the managed configuration file.
        group: System group that owns the managed configuration file.
    """

    def __init__(self, file: str | PathLike, /, mode: int, user: str, group: str) -> None:
        self._file = file
        self._mode = mode
        self._user = user
        self._group = group

    def load(self) -> Any:
        """Load the configuration file."""
        return self.__editor__.load(self._file)

    def dump(self, config: Any) -> None:
        """Dump a new configuration into the configuration file.

        Warnings:
            - This method will overwrite the entire content of the configuration file.
              If you just want to update the content of the current configuration file,
              use the `edit` method instead.
        """
        self.__editor__.dump(
            config, self._file, mode=self._mode, user=self._user, group=self._group
        )

    @contextmanager
    def edit(self) -> Iterator[Any]:
        """Edit the contents of the current configuration file."""
        with self.__editor__.edit(
            self._file, mode=self._mode, user=self._user, group=self._group
        ) as config:
            yield config

    @property
    def path(self) -> Path:
        """Get path to configuration file."""
        return Path(self._file)

    @property
    @abstractmethod
    def __editor__(self) -> BaseEditor:  # noqa D105
        raise NotImplementedError


class AcctGatherConfigManager(ConfigManager):
    """Manage the `acct_gather.conf` configuration file.

    Args:
        file: Path to the `acct_gather.conf` configuration file.
        user: System user that owns the `acct_gather.conf` configuration file.
        group: System group that owns the `acct_gather.conf` configuration file.
    """

    def __init__(self, file: str | PathLike, /, user: str, group: str) -> None:
        super().__init__(file, mode=0o600, user=user, group=group)

    @property
    def __editor__(self) -> AcctGatherConfigEditor:  # noqa D105
        return AcctGatherConfigEditor()


class CGroupConfigManager(ConfigManager):
    """Manage the `cgroup.conf` configuration file.

    Args:
        file: Path to the `cgroup.conf` configuration file.
        user: System user that owns the `cgroup.conf` configuration file. Default: "slurm"
        group: System group that owns the `cgroup.conf` configuration file. Default: "slurm"
    """

    def __init__(self, file: str | PathLike, /, user: str, group: str) -> None:
        super().__init__(file, mode=0o644, user=user, group=group)

    @property
    def __editor__(self) -> CGroupConfigEditor:  # noqa D105
        return CGroupConfigEditor()


class GresConfigManager(ConfigManager):
    """Manage the `gres.conf` configuration file.

    Args:
        file: Path to the `gres.conf` configuration file.
        user: System user that owns the `gres.conf` configuration file. Default: "slurm"
        group: System group that owns the `gres.conf` configuration file. Default: "slurm"
    """

    def __init__(self, file: str | PathLike, /, user: str, group: str) -> None:
        super().__init__(file, mode=0o644, user=user, group=group)

    @property
    def __editor__(self) -> GresConfigEditor:  # noqa D105
        return GresConfigEditor()


class OCIConfigManager(ConfigManager):
    """Manage the `oci.conf` configuration file.

    Args:
        file: Path to the `oci.conf` configuration file.
        user: System user that owns the `oci.conf` configuration file. Default: "slurm"
        group: System group that owns the `oci.conf` configuration file. Default: "slurm"
    """

    def __init__(self, file: str | PathLike, /, user: str, group: str) -> None:
        super().__init__(file, mode=0o644, user=user, group=group)

    @property
    def __editor__(self) -> OCIConfigEditor:  # noqa D105
        return OCIConfigEditor()


class SlurmConfigManager(ConfigManager):
    """Manage the `slurm.conf` configuration file.

    Args:
        file: Path to the `slurm.conf` configuration file.
        user: System user that owns the `slurm.conf` configuration file. Default: "slurm"
        group: System group that owns the `slurm.conf` configuration file. Default "slurm"
    """

    def __init__(self, file: str | PathLike, /, user: str, group: str) -> None:
        super().__init__(file, mode=0o644, user=user, group=group)

    @property
    def __editor__(self) -> SlurmConfigEditor:  # noqa D105
        return SlurmConfigEditor()


class SlurmdbdConfigManager(ConfigManager):
    """Manage the `slurmdbd.conf` configuration file.

    Args:
        file: Path to the `slurmdbd.conf` configuration file.
        user: System user that owns the `slurmdbd.conf` configuration file. Default: "slurm"
        group: System group that owns the `slurmdbd.conf` configuration file. Default: "slurm"
    """

    def __init__(self, file: str | PathLike, /, user: str, group: str) -> None:
        super().__init__(file, mode=0o600, user=user, group=group)

    @property
    def __editor__(self) -> SlurmdbdConfigEditor:  # noqa D105
        return SlurmdbdConfigEditor()
