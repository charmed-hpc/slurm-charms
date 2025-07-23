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

from collections.abc import Iterator
from contextlib import contextmanager
from os import PathLike
from pathlib import Path
from typing import Any

from slurmutils import BaseEditor


class SlurmConfigManager[T: type[BaseEditor]]:
    """Slurm configuration manager.

    Args:
        editor: Editor to use to manage configuration file.
        file: Path to the managed configuration file.
        mode: File access mode to assign the configuration file.
        user: System user that owns the managed configuration file.
        group: System group that owns the managed configuration file.
    """

    def __init__(
        self, editor: T, file: str | PathLike, mode: int, user: str, group: str
    ) -> None:
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

    @property
    def path(self) -> Path:
        """Get path to configuration file."""
        return Path(self._file)
