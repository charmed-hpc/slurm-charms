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

"""Manage Slurm's compute service, `slurmd`."""

__all__ = ["SlurmdManager"]

import json
import logging
from collections.abc import Iterable
from subprocess import CalledProcessError
from typing import Any, cast

import pynvml
from hpc_libs.machine import call
from hpc_libs.utils import plog
from slurmutils import Node

from slurm_ops import SlurmOpsError, scontrol
from slurm_ops.core import SLURMD_GROUP, SLURMD_USER, SlurmManager

_logger = logging.getLogger(__name__)


class SlurmdManager(SlurmManager):
    """Manage Slurm's compute service, `slurmd`."""

    def __init__(self, app_name: str, *, snap: bool = False) -> None:
        super().__init__("slurmd", snap)
        self._app_name = app_name

    @property
    def conf(self) -> Node:
        """Get the current node configuration."""
        options = self._load_options()
        return Node.from_str(options.get("--conf", ""))

    @conf.setter
    def conf(self, value: Node) -> None:
        _logger.info("updating compute node '%s' node configuration", self.name)

        _logger.debug("'%s' node configuration:\n%s", self.name, plog(value.dict()))
        with self._edit_options() as options:
            options["--conf"] = str(value)

        _logger.info("'%s' node configuration successfully updated", self.name)

    @conf.deleter
    def conf(self) -> None:
        with self._edit_options() as options:
            options.pop("--conf", None)

    @property
    def conf_server(self) -> list[str]:
        """Get the list of controller addresses `slurmd` uses to communicate with `slurmctld`."""
        options = self._load_options()
        return list(filter(None, options.get("--conf-server", "").split(",")))

    @conf_server.setter
    def conf_server(self, value: Iterable[str]) -> None:
        with self._edit_options() as options:
            options["--conf-server"] = ",".join(value)

    @conf_server.deleter
    def conf_server(self) -> None:
        with self._edit_options() as options:
            options.pop("--conf-server", None)

    @property
    def dynamic(self) -> bool:
        """Determine if this is a dynamic node."""
        options = self._load_options()
        return options.get("-Z", False)

    @dynamic.setter
    def dynamic(self, value: bool) -> None:
        with self._edit_options() as options:
            options["-Z"] = value

    @property
    def name(self) -> str:
        """Get the name that the compute node is registered under in Slurm."""
        options = self._load_options()
        return options.get("-N", "")

    @name.setter
    def name(self, value: str) -> None:
        with self._edit_options() as options:
            options["-N"] = value

    @property
    def user(self) -> str:
        """Get the user that the `slurmd` service runs as."""
        return SLURMD_USER

    @property
    def group(self) -> str:
        """Get the group that the `slurmd` service runs as."""
        return SLURMD_GROUP

    def get_gpu_info(self) -> list[str]:
        """Get the GPU devices on this node.

        Returns:
            A dict mapping model names to a list of device minor numbers. Model names are lowercase
            with whitespace replaced by underscores. For example:

            {'tesla_t4': [0, 1], 'l40s': [2, 3]}

            represents a node with two Tesla T4 GPUs at /dev/nvidia0 and /dev/nvidia1, and two L40S
            GPUs at /dev/nvidia2 and /dev/nvidia3.
        """
        gpu_info = {}
        try:
            pynvml.nvmlInit()

            gpu_count = pynvml.nvmlDeviceGetCount()
            for i in range(gpu_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)

                # Make model name lowercase and replace whitespace with underscores
                # to turn into a GRES-compatible format. For example, "Tesla T4" -> "tesla_t4",
                # which can be added as "Gres=gpu:tesla_t4:1".
                #
                # Aims to follow convention set by Slurm autodetect:
                # https://slurm.schedmd.com/gres.html#AutoDetect
                model = pynvml.nvmlDeviceGetName(handle)
                model = "_".join(model.split()).lower()

                minor_number = pynvml.nvmlDeviceGetMinorNumber(handle)
                gpu_info[model] = gpu_info.get(model, []) + [minor_number]

            pynvml.nvmlShutdown()
        except pynvml.NVMLError as e:
            _logger.info("no GPU info gathered: drivers cannot be detected")
            _logger.debug("NVML init failed with reason: %s", e)

        return [f"gpu:{model}:{len(devices)}" for model, devices in gpu_info.items()]

    def build_node(self) -> Node:
        """Build a new `Node` object from the output of `slurmd -C`.

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
        node.gres = self.get_gpu_info()

        # Delete `NodeName` as it cannot be set in the `--conf` flag.
        del node.node_name

        # Add application name to `Features` so that this node will be
        # added to the correct partition by Slurm.
        node.features = [self._app_name]

        return node

    def show_node(self) -> dict[str, Any]:
        """Get the output of `scontrol show node <nodename>` for this compute node.

        Raises:
            SlurmOpsError: Raised if `scontrol` fails to retrieve this compute node's information.

        Warnings:
            This method will always fail if this compute node is not registered with
            a Slurm controller.
        """
        result = scontrol("--json", "show", "node", self.name)
        info = json.loads(result[0])["nodes"][0]
        _logger.debug(
            "retrieved configuration for node '%s' from slurm with scontrol:\n%s",
            self.name,
            plog(info),
        )

        return info

    def delete(self) -> None:
        """Delete this compute node from Slurm.

        Raises:
            SlurmOpsError: Raised if a failure occurs when deleting this compute node from Slurm.
        """
        # FIXME: We need a better mechanism for guarding against situations where
        #   the `slurmd` units still have running jobs, but the cluster administrator
        #   is applying updates to the node configuration, or removing the node from the
        #   Charmed HPC cluster. Is it a documentation or technical issue?
        scontrol("delete", f"nodename={self.name}")

    def exists(self) -> bool:
        """Check if this compute node already exists in Slurm."""
        # A non-zero returncode means that the compute node doesn't exist in Slurm.
        return scontrol("show", "node", self.name, check=False)[1] == 0

    def reconfigure(self, *, state: str = "", reason: str = "") -> None:
        """Reconfigure the `slurmd` service running on the machine.

        Args:
            state: State to apply after the node is registered with Slurm.
            reason: Justification for the applied state after the node is registered with Slurm.

        Raises:
            SlurmOpsError: Raised if a failure occurs when reconfiguring the `slurmd` service.
        """
        super().reconfigure()
        if not state:
            return

        cmd = ["update", f"nodename={self.name}", f"state={state}"]
        if state != "idle":
            if reason:
                # Wrap reason with quotes if it isn't. Slurm requires reasons to be in quotes.
                if not (reason.startswith(("'", '"')) and reason.endswith(("'", '"'))):
                    reason = f"'{reason}'"
            else:
                reason = "'n/a'"

            cmd.append(f"reason={reason}")
        elif state == "idle" and reason:
            _logger.warning(
                "the 'idle' state does not require a reason to be set. "
                f"not updating node's {self.name} 'reason' field to '{reason}'."
            )

        _logger.info("setting state of node %s to state '%s'", self.name, state)
        scontrol(*cmd)
        _logger.info("successfully updated state of node %s to '%s'", self.name, state)
