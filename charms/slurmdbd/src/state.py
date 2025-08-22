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

"""Manage the state of the `slurmdbd` charmed operator."""

import logging
from typing import TYPE_CHECKING

import ops
from constants import (
    DATABASE_INTEGRATION_NAME,
    SLURMDBD_INTEGRATION_NAME,
)
from hpc_libs.interfaces import (
    ConditionEvaluation,
    controller_ready,
    integration_exists,
)

if TYPE_CHECKING:
    from charm import SlurmdbdCharm

_logger = logging.getLogger(__name__)


def slurmdbd_installed(charm: "SlurmdbdCharm") -> ConditionEvaluation:
    """Check if `slurmdbd` is installed on the unit."""
    installed = charm.slurmdbd.is_installed()
    return ConditionEvaluation(
        installed,
        "`slurmdbd` is not installed. See `juju debug-log` for details" if not installed else "",
    )


database_exists = integration_exists(DATABASE_INTEGRATION_NAME)
database_exists.__doc__ = """Check if the `database` integration exists."""


def database_ready(charm: "SlurmdbdCharm") -> ConditionEvaluation:
    """Check if the `slurmdbd` accounting database has been created."""
    exists = charm.database.is_resource_created()
    return ConditionEvaluation(exists, "Waiting for database creation" if not exists else "")


def slurmdbd_ready(charm: "SlurmdbdCharm") -> bool:
    """Check if the `slurmdbd` service is ready to start.

    Required conditions:
        1. `database` integration is ready.
        2. `slurmctld` integration is ready.
        3. Slurm authentication key exists on the unit.
        4. Slurm JWT key exists on the unit.
    """
    return all(
        (
            controller_ready(charm).ok,
            database_ready(charm).ok,
            charm.slurmdbd.key.path.exists(),
            charm.slurmdbd.jwt.path.exists(),
        )
    )


def check_slurmdbd(charm: "SlurmdbdCharm") -> ops.StatusBase:
    """Determine the state of the `slurmdbd` application/unit based on satisfied conditions."""
    ok, message = slurmdbd_installed(charm)
    if not ok:
        return ops.BlockedStatus(message)

    missing_integrations = {
        SLURMDBD_INTEGRATION_NAME: not charm.slurmctld.is_joined(),
        DATABASE_INTEGRATION_NAME: not database_exists(charm).ok,
    }
    if any(missing_integrations.values()):
        return ops.BlockedStatus(
            "Waiting for integrations: ["
            + ", ".join(f"`{name}`" for name, missing in missing_integrations.items() if missing)
            + "]"
        )

    if not charm.slurmdbd.service.is_active():
        return ops.WaitingStatus("Waiting for `slurmdbd` to start")

    return ops.ActiveStatus()
