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

"""Manage the state of the `slurmctld` charmed operator."""

from typing import TYPE_CHECKING

import ops
from hpc_libs.interfaces import ConditionEvaluation

if TYPE_CHECKING:
    from charm import SlurmctldCharm


def slurmctld_installed(charm: "SlurmctldCharm") -> ConditionEvaluation:
    """Check if `slurmctld` is installed on the unit."""
    installed = charm.slurmctld.is_installed()
    return ConditionEvaluation(
        installed,
        "`slurmctld` is not installed. See `juju debug-log` for details" if not installed else "",
    )


def cluster_name_set(charm: "SlurmctldCharm") -> ConditionEvaluation:
    """Check if the cluster name has been set."""
    try:
        name_set = charm.slurmctld_peer.cluster_name != ""
    except ops.RelationNotFoundError:
        name_set = False

    return ConditionEvaluation(
        name_set, "Waiting for the cluster name to be set" if not name_set else ""
    )


def config_ready(charm: "SlurmctldCharm") -> ConditionEvaluation:
    """Check if the `slurm.conf` file is ready to shared with other applications."""
    ready = charm.slurmctld.config.exists()
    return ConditionEvaluation(
        ready, "Waiting for Slurm configuration to be updated" if not ready else ""
    )


def slurmctld_ready(charm: "SlurmctldCharm") -> bool:
    """Check if the `slurmctld` service is ready to integrate with other applications.

    Required conditions:
        1. `slurmctld` is installed on the unit.
        2. Cluster name is set in the `slurmctld-peer` integration.
        3. `slurmctld` service is active.
    """
    return all(
        (
            slurmctld_installed(charm).ok,
            cluster_name_set(charm).ok,
            charm.slurmctld.service.is_active(),
        )
    )


def check_slurmctld(charm: "SlurmctldCharm") -> ops.StatusBase:
    """Determine the state of the `slurmctld` application/unit based on satisfied conditions."""
    ok, message = slurmctld_installed(charm)
    if not ok:
        return ops.BlockedStatus(message)

    ok, message = cluster_name_set(charm)
    if not ok:
        return ops.WaitingStatus(message)

    if not charm.slurmctld.service.is_active():
        return ops.WaitingStatus("Waiting for `slurmctld` to start")

    return ops.ActiveStatus()
