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

"""Control Slurm using `scontrol ...` commands."""

__all__ = ["scontrol"]

from subprocess import CalledProcessError
from typing import Any

from hpc_libs.machine import call

from slurm_ops.core import SlurmOpsError


def scontrol(*args: str, **kwargs: Any) -> tuple[str, int]:  # noqa D417
    """Control Slurm using `scontrol ...` commands.

    Keyword Args:
        stdin: Standard input to pipe to the `snap` command.
        check:
            If set to `True`, raise an error if the `snap` command
            exits with a non-zero exit code. Default: True

    Raises:
        SlurmOpsError: Raised if a `scontrol` command fails and check is set to `True`.
    """
    try:
        result = call("scontrol", *args, **kwargs)
    except CalledProcessError as e:
        raise SlurmOpsError(
            f"scontrol command '{e.cmd}' failed with exit code {e.returncode}. "
            + f"reason: {e.stderr}"
        )

    return result.stdout, result.returncode
