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

"""Manage the configuration of the `slurmd` charmed operator."""

import logging
from collections.abc import Callable
from enum import Enum
from functools import wraps
from pathlib import Path
from subprocess import CalledProcessError
from typing import TYPE_CHECKING, Any, cast

import ops
from gpu import get_all_gpu
from hpc_libs.interfaces import ComputeData
from hpc_libs.machine import call
from hpc_libs.utils import StopCharm, plog
from slurm_ops import SlurmOpsError
from slurmutils import ModelError, Node, Partition
from state import slurmd_ready

if TYPE_CHECKING:
    from charm import SlurmdCharm

_logger = logging.getLogger(__name__)


class State(Enum):
    """Configurable node states."""

    DOWN = "down"
    IDLE = "idle"


def reboot_if_required(charm: ops.CharmBase, /, now: bool = False) -> None:
    """Perform a reboot of the unit if required, e.g. following a driver installation."""
    if Path("/var/run/reboot-required").exists():
        _logger.info("rebooting unit '%s'", charm.unit.name)
        charm.unit.reboot(now)


def get_node_info() -> Node:
    """Get machine info as reported by `slurmd -C`.

    For details see: https://slurm.schedmd.com/slurmd.html

    Raises:
        SlurmOpsError: Raised if the command `slurmd -C` fails.
    """
    try:
        result = call("slurmd", "-C")
    except CalledProcessError as e:
        _logger.error(e)
        raise SlurmOpsError(
            (
                f"slurmd command '{e.cmd}' failed with exit code {e.returncode}. "
                + f"reason: {e.stderr}"
            )
        )

    node = Node.from_str(result.stdout.splitlines()[:-1][0])

    # Set the `MemSpecLimit` for this node. This memory allocation will be reserved for
    # the services and other operations-related routines running on this unit.
    # We know `RealMemory` is type `int` because it is returned by `slurmd -C`.
    node.mem_spec_limit = min(1024, cast(int, node.real_memory) // 2)

    # Detect if there are any additional GPU resources on this unit.
    if gpus := get_all_gpu():
        node.gres = []
        for model, devices in gpus.items():
            node.gres.append(f"gpu:{model}:{len(devices)}")

    return node


def get_partition(charm: "SlurmdCharm") -> Partition:
    """Get the current partition configuration.

    Raises:
        SlurmOpsError: Raised if the partition configuration fails to load.
    """
    try:
        partition = Partition.from_str(cast(str, charm.config.get("partition-config", "")))
        partition.partition_name = charm.app.name
        partition.nodes = [charm.app.name]
    except (ModelError, ValueError) as e:
        _logger.error(
            "failed to load partition configuration for '%s'. reason:\n%s",
            charm.app.name,
            e,
        )
        raise SlurmOpsError("failed to load partition configuration")

    return partition


def set_partition(charm: "SlurmdCharm", /, partition: Partition) -> None:
    """Set partition configuration."""
    if charm.slurmctld.is_joined():
        charm.unit.status = ops.MaintenanceStatus("Updating partition configuration")
        _logger.info("updating '%s' partition configuration", charm.app.name)
        _logger.debug("'%s' partition configuration:\n%s", charm.app.name, plog(partition.dict()))
        charm.slurmctld.set_compute_data(ComputeData(partition=partition))
        _logger.info("'%s' partition configuration successfully updated", charm.app.name)
    else:
        _logger.info(
            (
                "partition '%s' is not connected to a slurm controller. "
                + "skipping partition configuration update"
            ),
            charm.app.name,
        )


def reconfigure(func: Callable[..., Any]) -> Callable[..., Any]:
    """Reconfigure the `slurmd` service."""

    @wraps(func)
    def wrapper(charm: "SlurmdCharm", *args: Any, **kwargs: Any) -> Any:
        func(charm, *args, **kwargs)

        if not slurmd_ready(charm) or not charm.service_needs_restart:
            return

        _logger.info("updating unit '%s' node configuration", charm.unit.name)
        node = get_node_info()
        del node.node_name  # `NodeName` cannot be set in the `--conf` flag.
        node.features = [charm.app.name]
        node.update(Node(charm.stored.custom_node_config))

        # Reset state if the `slurmd` service is "cold booting". E.g. the `slurmd` service is being
        # restarted after an arbitrary period of downtime for maintenance.
        if not charm.slurmd.service.is_active():
            state = charm.stored.default_state
            if state not in (states := [member.value for member in State]):
                raise SlurmOpsError(
                    f"invalid default state `{charm}` provided. "
                    + f"valid states are {[', '.join(states)]}"
                )

            if state != "idle":
                # `idle` is not a valid state configuration for the `--conf` flag,
                # but is a valid state within `slurmctld`.
                #
                # For details see: https://slurm.schedmd.com/slurm.conf.html#OPT_State
                node.state = state
                node.reason = charm.stored.default_reason

            _logger.info("setting the default state of node '%s' to '%s'", charm.unit.name, state)

        _logger.debug("'%s' node configuration:\n%s", charm.unit.name, plog(node.dict()))
        charm.slurmd.conf = node
        _logger.info("'%s' node configuration successfully updated", charm.unit.name)

        try:
            charm.slurmd.service.enable()
            charm.slurmd.service.restart()
        except SlurmOpsError as e:
            _logger.error(e.message)
            raise StopCharm(
                ops.BlockedStatus("Failed to start `slurmd`. See `juju debug-log` for details")
            )

    return wrapper
