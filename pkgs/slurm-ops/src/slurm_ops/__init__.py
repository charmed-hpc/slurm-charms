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

"""Manage Slurm service operations on machines."""

__all__ = [
    # From `core` module
    "SLURM_GROUP",
    "SLURM_USER",
    "SLURMD_GROUP",
    "SLURMD_USER",
    "SLURMRESTD_GROUP",
    "SLURMRESTD_USER",
    "SlurmOpsError",
    # From `sackd.py`
    "SackdManager",
    # From `scontrol.py`
    "scontrol",
    # From `slurmctld.py`
    "SlurmctldManager",
    # From `slurmd.py`
    "SlurmdManager",
    # From `slurmdbd.py`
    "SlurmdbdManager",
    # From `slurmrestd.py`
    "SlurmrestdManager",
]

from .core import (
    SLURM_GROUP,
    SLURM_USER,
    SLURMD_GROUP,
    SLURMD_USER,
    SLURMRESTD_GROUP,
    SLURMRESTD_USER,
    SlurmOpsError,
)
from .sackd import SackdManager
from .scontrol import scontrol
from .slurmctld import SlurmctldManager
from .slurmd import SlurmdManager
from .slurmdbd import SlurmdbdManager
from .slurmrestd import SlurmrestdManager
