# Copyright 2024-2025 Canonical Ltd.
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

"""Query information about the underlying Juju machine."""

import logging
import subprocess

from hpc_libs.machine import call
from slurm_ops import SlurmOpsError
from slurmutils import Node

from .gpu import get_all_gpu

_logger = logging.getLogger(__name__)


def get_node_info() -> Node:
    """Get machine info as reported by `slurmd -C`.

    For details see: https://slurm.schedmd.com/slurmd.html

    Raises:
        SlurmOpsError: Raised if the command `slurmd -C` fails.
    """
    try:
        result = call("slurmd", "-C")
    except subprocess.CalledProcessError as e:
        _logger.error(e)
        raise SlurmOpsError(
            (
                f"slurmd command '{e.cmd}' failed with exit code {e.returncode}. "
                + f"reason: {e.stderr}"
            )
        )

    node = Node.from_str(result.stdout.splitlines()[:-1][0])

    # Set `memspeclimit` for this node. This memory allocation will be reserved for
    # the services and other operations-related routines running on this unit.
    node.mem_spec_limit = min(1024, node.real_memory // 2)

    # Detect if there are any additional GPU resources on this unit.
    if gpus := get_all_gpu():
        node.gres = []
        for model, devices in gpus.items():
            node.gres.append(f"gpu:{model}:{len(devices)}")

    return node
