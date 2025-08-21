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

import shutil
from collections.abc import Iterator, Mapping, Iterable
from contextlib import contextmanager
from os import PathLike
from pathlib import Path
from types import MappingProxyType
from typing import Any

from slurmutils import BaseEditor


class IncludeMapping[T: type[BaseEditor]](Mapping):
    def __init__(
        self,
        includes: Iterable[Path],
        /,
        editor: T,
        path: Path,
        *,
        mode: int,
        user: str,
        group: str,
    ) -> None:
        self._editor = editor
        self._path = path
        self._mode = mode
        self._user = user
        self._group = group

        self._data = {
            p.name: SlurmConfigManager(
                self._editor,
                file=p,
                mode=self._mode,
                user=self._user,
                group=self._group,
            )
            for p in includes
        }

    def __getitem__(self, key, /) -> "SlurmConfigManager":
        try:
            return self._data[key]
        except KeyError:
            return self.__missing__(key)

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __missing__(self, key: str) -> "SlurmConfigManager":
        return SlurmConfigManager(
            self._editor,
            Path(self._path) / key,
            mode=self._mode,
            user=self._user,
            group=self._group,
        )


class SlurmConfigManager[T: type[BaseEditor]]:
    """Slurm configuration manager.

    Args:
        editor: Editor to use to manage configuration file.
        file: Path to the managed configuration file.
        mode: File access mode to assign the configuration file.
        user: System user that owns the managed configuration file.
        group: System group that owns the managed configuration file.
    """

    def __init__(self, editor: T, file: str | PathLike, mode: int, user: str, group: str) -> None:
        # Cast to `Any` as we only want `editor` to be subtype of `BaseEditor`,
        # but not be a `BaseEditor` object.
        self._editor: Any = editor()
        self._file = file
        self._mode = mode
        self._user = user
        self._group = group

    def load(self) -> Any:
        """Load the configuration file."""
        return self._editor.load(self._file)

    def dump(self, config: Any) -> None:
        """Dump a new configuration into the configuration file.

        Warnings:
            - This method will overwrite the entire content of the configuration file.
              If you just want to update the content of the current configuration file,
              use the `edit` method instead.
        """
        self._editor.dump(config, self._file, mode=self._mode, user=self._user, group=self._group)

    @contextmanager
    def edit(self) -> Iterator[Any]:
        """Edit the contents of the current configuration file."""
        with self._editor.edit(
            self._file, mode=self._mode, user=self._user, group=self._group
        ) as config:
            yield config

    def merge(self) -> None:
        """Merge 'include' files into the main configuration file."""
        includes = [include.load() for include in self.includes.values()]
        with self.edit() as config:
            for include in includes:
                config.update(include)

    def save(self) -> None:
        """Create a snapshot of the current configuration file."""
        for p in [self.path] + [include.path for include in self.includes.values()]:
            try:
                shutil.copy(p, p.with_suffix(p.suffix + ".snapshot"))
            except FileNotFoundError:
                pass

    def restore(self) -> None:
        """Restore the current configuration file from a snapshot."""
        for snapshot in self.snapshots.values():
            shutil.copy(snapshot.path, snapshot.path.parent / snapshot.path.stem)

    def exists(self) -> bool:
        """Check whether the configuration file exists."""
        return self.path.exists()

    def delete(self) -> None:
        """Delete the configuration file."""
        self.path.unlink(missing_ok=True)

    @property
    def path(self) -> Path:
        """Get path to configuration file."""
        return Path(self._file)

    @property
    def includes(self) -> MappingProxyType[str, "SlurmConfigManager"]:
        """Get paths to additional configuration files."""
        return MappingProxyType(
            IncludeMapping(
                [
                    p
                    for p in self.path.parent.glob(f"{self.path.name}.*")
                    if p.suffix != ".snapshot"
                ],
                self._editor.__class__,
                path=self.path.parent,
                mode=self._mode,
                user=self._user,
                group=self._group,
            )
        )

    @property
    def snapshots(self) -> MappingProxyType[str, "SlurmConfigManager"]:
        """Get paths to configuration file snapshots."""
        return MappingProxyType(
            {
                p.name: SlurmConfigManager(
                    self._editor.__class__,
                    file=p,
                    mode=self._mode,
                    user=self._user,
                    group=self._group,
                )
                for p in self.path.parent.glob(f"{self.path.name}*.snapshot")
            }
        )
