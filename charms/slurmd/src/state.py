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

"""Manage the state of the `slurmd` charmed operator."""

from typing import TYPE_CHECKING

import ops
from constants import SLURMD_INTEGRATION_NAME
from hpc_libs.interfaces import ConditionEvaluation, controller_not_ready

if TYPE_CHECKING:
    from charm import SlurmdCharm


def slurmd_not_installed(charm: "SlurmdCharm") -> ConditionEvaluation:
    """Check if `slurmd` is installed on the unit."""
    not_installed = not charm.slurmd.is_installed()
    return (
        not_installed,
        "`slurmd` is not installed. See `juju debug-log` for details" if not_installed else "",
    )


def slurmd_ready(charm: "SlurmdCharm") -> bool:
    """Check if the `slurmd` service is ready to start.

    Required conditions:
        1. `slurmctld` integration is ready.
        2.  Slurm authentication key exists on the unit.
    """
    return all(
        (
            not controller_not_ready(charm)[0],
            charm.slurmd.key.path.exists(),
        )
    )


def check_slurmd(charm: "SlurmdCharm") -> ops.StatusBase:
    """Determine the state of the `slurmd` application/unit based on satisfied conditions."""
    condition, msg = slurmd_not_installed(charm)
    if condition:
        return ops.BlockedStatus(msg)

    if not charm.slurmctld.is_joined():
        return ops.BlockedStatus(f"Waiting for integrations: [`{SLURMD_INTEGRATION_NAME}`]")

    if not charm.slurmd.service.is_active():
        return ops.WaitingStatus("Waiting for `slurmd` to start")

    return ops.ActiveStatus()
