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
    controller_not_ready,
    integration_not_exists,
)

if TYPE_CHECKING:
    from charm import SlurmdbdCharm

_logger = logging.getLogger(__name__)


def slurmdbd_not_installed(charm: "SlurmdbdCharm") -> ConditionEvaluation:
    """Check if `slurmdbd` is installed on the unit."""
    not_installed = not charm.slurmdbd.is_installed()
    return (
        not_installed,
        "`slurmdbd` is not installed. See `juju debug-log` for details" if not_installed else "",
    )


database_not_exists = integration_not_exists(DATABASE_INTEGRATION_NAME)
database_not_exists.__doc__ = """Check if the `database` does not exist"""


def database_not_ready(charm: "SlurmdbdCharm") -> ConditionEvaluation:
    """Check if the `slurmdbd` accounting database has been created."""
    not_exists = not charm.database.is_resource_created()
    return not_exists, "Waiting for database creation" if not_exists else ""


def check_slurmdbd(charm: "SlurmdbdCharm") -> ops.StatusBase:
    """Determine the state of the `slurmdbd` application/unit based on satisfied conditions."""
    condition, msg = slurmdbd_not_installed(charm)
    if condition:
        return ops.BlockedStatus(msg)

    missing_integrations = {
        SLURMDBD_INTEGRATION_NAME: not charm.slurmctld.is_joined(),
        DATABASE_INTEGRATION_NAME: database_not_exists(charm)[0],
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
            not controller_not_ready(charm)[0],
            not database_not_ready(charm)[0],
            charm.slurmdbd.key.path.exists(),
            charm.slurmdbd.jwt.path.exists(),
        )
    )
