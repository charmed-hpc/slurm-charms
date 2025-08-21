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

"""Manage the state of the `slurmrestd` charmed operator."""

from typing import TYPE_CHECKING

import ops
from constants import SLURMRESTD_INTEGRATION_NAME
from hpc_libs.interfaces import ConditionEvaluation

if TYPE_CHECKING:
    from charm import SlurmrestdCharm


def slurmrestd_not_installed(charm: "SlurmrestdCharm") -> ConditionEvaluation:
    """Check if `slurmrestd` is installed on the unit."""
    not_installed = not charm.slurmrestd.is_installed()
    return (
        not_installed,
        "`slurmrestd` is not installed. See `juju debug-log` for details" if not_installed else "",
    )


def check_slurmrestd(charm: "SlurmrestdCharm") -> ops.StatusBase:
    """Determine the state of the `slurmrestd` application/unit based on satisfied conditions."""
    condition, msg = slurmrestd_not_installed(charm)
    if condition:
        return ops.BlockedStatus(msg)

    if not charm.slurmctld.is_joined():
        return ops.BlockedStatus(f"Waiting for integrations: [`{SLURMRESTD_INTEGRATION_NAME}`]")

    if not charm.slurmrestd.service.is_active() and charm.slurmctld.is_joined():
        return ops.WaitingStatus("Waiting for `slurmrestd` to start")

    if not charm.slurmrestd.service.is_active():
        return ops.BlockedStatus("`slurmrestd` is not running")

    return ops.ActiveStatus()
