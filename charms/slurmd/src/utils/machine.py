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

"""Query information about the underlying Juju machine."""

import logging
import subprocess
from typing import Any, Dict

_logger = logging.getLogger(__name__)


def get_slurmd_info() -> Dict[str, Any]:
    """Get machine info as reported by `slurmd -C`."""
    try:
        r = subprocess.check_output(["slurmd", "-C"], text=True).strip()
    except subprocess.CalledProcessError as e:
        _logger.error(e)
        raise

    info = {}
    for opt in r.split()[:-1]:
        key, value = opt.split("=")
        # Split comma-separated lists, e.g. Gres=gpu:model_a:1,gpu:model_b:1
        if "," in value:
            info[key] = value.split(",")
        else:
            info[key] = value
    return info
