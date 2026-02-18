# Copyright 2025-2026 Canonical Ltd.
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

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import ops
from constants import SLURMD_INTEGRATION_NAME
from hpc_libs.interfaces import ConditionEvaluation, controller_ready

if TYPE_CHECKING:
    from charm import SlurmdCharm

_logger = logging.getLogger(__name__)


def slurmd_installed(charm: "SlurmdCharm") -> ConditionEvaluation:
    """Check if `slurmd` is installed on the unit."""
    installed = charm.slurmd.is_installed()
    return ConditionEvaluation(
        installed,
        "`slurmd` is not installed. See `juju debug-log` for details" if not installed else "",
    )


def slurmd_ready(charm: "SlurmdCharm") -> bool:
    """Check if the `slurmd` service is ready to start.

    Required conditions:
        1. `slurmctld` integration is ready.
        2.  Slurm authentication key exists on the unit.
    """
    return all(
        (
            controller_ready(charm).ok,
            charm.slurmd.key.path.exists(),
        )
    )


def check_slurmd(charm: "SlurmdCharm") -> ops.StatusBase:
    """Determine the state of the `slurmd` application/unit based on satisfied conditions."""
    ok, message = slurmd_installed(charm)
    if not ok:
        return ops.BlockedStatus(message)

    if not charm.slurmctld.is_joined():
        return ops.BlockedStatus(f"Waiting for integrations: [`{SLURMD_INTEGRATION_NAME}`]")

    if not charm.slurmd.service.is_active():
        return ops.WaitingStatus("Waiting for `slurmd` to start")

    return ops.ActiveStatus()


def reboot_if_required(charm: "SlurmdCharm", *, now: bool = False) -> None:
    """Perform a reboot of the unit if required, such as following a driver installation."""
    if Path("/var/run/reboot-required").exists():
        _logger.info("rebooting unit '%s'", charm.unit.name)
        charm.unit.reboot(now)
