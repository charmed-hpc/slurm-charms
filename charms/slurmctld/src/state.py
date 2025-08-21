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


def slurmctld_not_installed(charm: "SlurmctldCharm") -> ConditionEvaluation:
    """Check if `slurmctld` is installed on the unit."""
    not_installed = not charm.slurmctld.is_installed()
    return (
        not_installed,
        "`slurmctld` is not installed. See `juju debug-log` for details" if not_installed else "",
    )


def cluster_name_not_set(charm: "SlurmctldCharm") -> ConditionEvaluation:
    """Check if the cluster name has been set."""
    try:
        not_set = not charm.slurmctld_peer.cluster_name
    except ops.RelationNotFoundError:
        not_set = True

    return not_set, "Waiting for the cluster name to be set" if not_set else ""


def slurmctld_ready(charm: "SlurmctldCharm") -> bool:
    """Check if the `slurmctld` service is ready to integrate with other applications.

    Required conditions:
        1. `slurmctld` is installed on the unit.
        2. Cluster name is set in the `slurmctld-peer` integration.
        3. `slurmctld` service is active.
    """
    return all(
        (
            not slurmctld_not_installed(charm)[0],
            not cluster_name_not_set(charm)[0],
            charm.slurmctld.service.is_active(),
        )
    )


def check_slurmctld(charm: "SlurmctldCharm") -> ops.StatusBase:
    """Determine the state of the `slurmctld` application/unit based on satisfied conditions."""
    condition, msg = slurmctld_not_installed(charm)
    if condition:
        return ops.BlockedStatus(msg)

    condition, msg = cluster_name_not_set(charm)
    if condition:
        return ops.WaitingStatus(msg)

    if not charm.slurmctld.service.is_active():
        return ops.WaitingStatus("Waiting for `slurmctld` to start")

    return ops.ActiveStatus()
