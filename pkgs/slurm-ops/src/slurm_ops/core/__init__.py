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

"""Core utilities for composing Slurm operations managers."""

__all__ = [
    # From `base.py`
    "SlurmManager",
    # From `config.py`
    "AcctGatherConfigManager",
    "CGroupConfigManager",
    "GresConfigManager",
    "OCIConfigManager",
    "SlurmConfigManager",
    "SlurmdbdConfigManager",
    # From `constants.py`
    "SLURM_USER",
    "SLURM_GROUP",
    "SLURMD_USER",
    "SLURMD_GROUP",
    "SLURMRESTD_USER",
    "SLURMRESTD_GROUP",
    # From `errors.py`
    "SlurmOpsError",
    # From `options.py`
    "marshal_options",
    "parse_options",
]

from .base import SlurmManager
from .config import (
    AcctGatherConfigManager,
    CGroupConfigManager,
    GresConfigManager,
    OCIConfigManager,
    SlurmConfigManager,
    SlurmdbdConfigManager,
)
from .constants import (
    SLURM_GROUP,
    SLURM_USER,
    SLURMD_GROUP,
    SLURMD_USER,
    SLURMRESTD_GROUP,
    SLURMRESTD_USER,
)
from .errors import SlurmOpsError
from .options import marshal_options, parse_options
