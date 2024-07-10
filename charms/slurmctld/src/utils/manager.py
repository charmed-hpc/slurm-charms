# Copyright 2024 Canonical Ltd.
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

"""Manage slurmctld service operations on machine."""

import logging
import subprocess

from charms.hpc_libs.v0.slurm_ops import ServiceType, SlurmManagerBase, SlurmOpsError

_logger = logging.getLogger(__name__)


def scontrol(*args: str) -> None:
    """Control Slurm cluster via executing `scontrol ...` commands on machine.

    Args:
        args: Arguments to pass to `scontrol`.

    Raises:
        SlurmOpsError: Raised if `scontrol` command execution fails.
    """
    cmd = ["scontrol", *args]
    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        _logger.error(
            "scontrol failed:\ncmd: %s\nreturncode: %d\noutput: %s",
            e.cmd,
            e.returncode,
            e.stdout.decode(),
        )
        raise SlurmOpsError(
            f"scontrol command {' '.join(cmd)}` failed with returncode {e.returncode}"
        )


class SlurmctldManager(SlurmManagerBase):
    """Manage slurmctld service operations."""

    def __init__(self) -> None:
        super().__init__(service=ServiceType.SLURMCTLD)
