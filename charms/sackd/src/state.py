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

"""Manage the state of the `sackd` charmed operator."""

from typing import TYPE_CHECKING

import ops
from constants import SACKD_INTEGRATION_NAME
from hpc_libs.interfaces import ConditionEvaluation

if TYPE_CHECKING:
    from charm import SackdCharm


def sackd_installed(charm: "SackdCharm") -> ConditionEvaluation:
    """Check if `sackd` is installed on the unit."""
    installed = charm.sackd.is_installed()
    return ConditionEvaluation(
        installed,
        "`sackd` is not installed. See `juju debug-log` for details" if not installed else "",
    )


def check_sackd(charm: "SackdCharm") -> ops.StatusBase:
    """Determine the state of the `sackd` application/unit based on satisfied conditions."""
    ok, message = sackd_installed(charm)
    if not ok:
        return ops.BlockedStatus(message)

    if not charm.slurmctld.is_joined():
        return ops.BlockedStatus(f"Waiting for integrations: [`{SACKD_INTEGRATION_NAME}`]")

    if not charm.sackd.service.is_active():
        return ops.WaitingStatus("Waiting for `sackd` to start")

    return ops.ActiveStatus()
