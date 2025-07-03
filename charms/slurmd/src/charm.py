#!/usr/bin/env python3
# Copyright 2020-2024 Omnivector, LLC.
# See LICENSE file for licensing details.

"""Slurmd Operator Charm."""

import logging
from pathlib import Path
from typing import Any, Dict, cast

from constants import SLURMD_PORT
from hpc_libs.slurm_ops import SlurmdManager, SlurmOpsError
from interface_slurmctld import Slurmctld, SlurmctldAvailableEvent
from ops import (
    ActionEvent,
    ActiveStatus,
    BlockedStatus,
    CharmBase,
    ConfigChangedEvent,
    InstallEvent,
    MaintenanceStatus,
    StoredState,
    UpdateStatusEvent,
    WaitingStatus,
    main,
)
from slurmutils import calculate_rs
from slurmutils.models.option import NodeOptionSet, PartitionOptionSet
from utils import gpu, machine, nhc, rdma, service

from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v0.juju_systemd_notices import (  # type: ignore[import-untyped]
    ServiceStartedEvent,
    ServiceStoppedEvent,
    SystemdNotices,
)

logger = logging.getLogger(__name__)


class SlurmdCharm(CharmBase):
    """Slurmd lifecycle events."""

    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        """Init _stored attributes and interfaces, observe events."""
        super().__init__(*args, **kwargs)

        self._stored.set_default(
            auth_key=str(),
            new_node=True,
            nhc_conf=str(),
            nhc_params=str(),
            slurm_installed=False,
            slurmctld_available=False,
            slurmctld_hosts=str(),
            user_supplied_node_parameters={},
            user_supplied_partition_parameters={},
        )

        self._slurmd = SlurmdManager(snap=False)
        self._slurmctld = Slurmctld(self, "slurmctld")
        self._systemd_notices = SystemdNotices(self, ["slurmd"])
        self._grafana_agent = COSAgentProvider(self)

        event_handler_bindings = {
            self.on.install: self._on_install,
            self.on.update_status: self._on_update_status,
            self.on.config_changed: self._on_config_changed,
            self._slurmctld.on.slurmctld_available: self._on_slurmctld_available,
            self._slurmctld.on.slurmctld_unavailable: self._on_slurmctld_unavailable,
            self.on.service_slurmd_started: self._on_slurmd_started,
            self.on.service_slurmd_stopped: self._on_slurmd_stopped,
            self.on.node_configured_action: self._on_node_configured_action,
            self.on.node_config_action: self._on_node_config_action_event,
        }
        for event, handler in event_handler_bindings.items():
            self.framework.observe(event, handler)

    def _on_install(self, event: InstallEvent) -> None:
        """Perform installation operations for slurmd."""
        # Account for case where base image has been auto-upgraded by Juju and a reboot is pending
        # before charm code runs. Reboot "now", before the current hook completes, and restart the
        # hook after reboot. Prevents issues such as drivers/kernel modules being installed for a
        # running kernel pending replacement by a newer version on reboot.
        self._reboot_if_required(now=True)

        self.unit.status = MaintenanceStatus("Installing slurmd")

        try:
            self._slurmd.install()

            self.unit.status = MaintenanceStatus("Installing nhc")
            nhc.install()

            self.unit.status = MaintenanceStatus("Installing RDMA packages")
            rdma.install()

            self.unit.status = MaintenanceStatus("Detecting if machine is GPU-equipped")
            gpu_enabled = gpu.autoinstall()
            if gpu_enabled:
                self.unit.status = MaintenanceStatus("Successfully installed GPU drivers")
            else:
                self.unit.status = MaintenanceStatus("No GPUs found. Continuing")

            self.unit.set_workload_version(self._slurmd.version())
            # TODO: https://github.com/orgs/charmed-hpc/discussions/10 -
            #  Evaluate if we should continue doing the service override here
            #  for `juju-systemd-notices`.
            service.override_service()
            self._systemd_notices.subscribe()

            self._slurmd.service.enable()

            self._stored.slurm_installed = True
        except (SlurmOpsError, gpu.GPUOpsError) as e:
            logger.error(e.message)
            event.defer()

        self.unit.open_port("tcp", SLURMD_PORT)

        self._check_status()
        self._reboot_if_required()

    def _on_config_changed(self, _: ConfigChangedEvent) -> None:
        """Handle charm configuration changes."""
        # Casting the type to str is required here because `get` returns a looser
        # type than what `nhc.generate_config(...)` allows to be passed.
        if nhc_conf := cast(str, self.model.config.get("nhc-conf", "")):
            if nhc_conf != self._stored.nhc_conf:
                self._stored.nhc_conf = nhc_conf
                nhc.generate_config(nhc_conf)

        user_supplied_partition_parameters = self.model.config.get("partition-config")

        if self.model.unit.is_leader():
            if user_supplied_partition_parameters is not None:
                try:
                    tmp_params = {
                        item.split("=")[0]: item.split("=")[1]
                        for item in str(user_supplied_partition_parameters).split()
                    }
                except IndexError:
                    logger.error(
                        "Error parsing partition-config. Please use KEY1=VALUE KEY2=VALUE."
                    )
                    return

                # Validate the user supplied params are valid params.
                for parameter in tmp_params:
                    if parameter not in list(PartitionOptionSet.keys()):
                        logger.error(
                            f"Invalid user supplied partition configuration parameter: {parameter}."
                        )
                        return

                self._stored.user_supplied_partition_parameters = tmp_params

                if self._slurmctld.is_joined:
                    self._slurmctld.set_partition()

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handle update status."""
        self._check_status()

    def _on_slurmctld_available(self, event: SlurmctldAvailableEvent) -> None:
        """Retrieve the slurmctld_available event data and store in charm state."""
        if self._stored.slurm_installed is not True:
            event.defer()
            return

        if (slurmctld_hosts := event.slurmctld_hosts) != self._stored.slurmctld_hosts:
            if slurmctld_hosts is not None:
                # config server has format e.g. juju-532a19-0:6817,juju-532a19-1:6817
                self._slurmd.config_server = ",".join(f"{host}:6817" for host in slurmctld_hosts)
                self._stored.slurmctld_hosts = slurmctld_hosts
                logger.debug(f"slurmctld_hosts={slurmctld_hosts}")
            else:
                logger.debug("'slurmctld_hosts' not in event data.")
                return

        if (auth_key := event.auth_key) != self._stored.auth_key:
            if auth_key is not None:
                self._stored.auth_key = auth_key
                self._slurmd.key.set(auth_key)
            else:
                logger.debug("'auth_key' not in event data.")
                return

        if (nhc_params := event.nhc_params) != self._stored.nhc_params:
            if nhc_params is not None:
                self._stored.nhc_params = nhc_params
                nhc.generate_wrapper(nhc_params)
                logger.debug(f"nhc_params={nhc_params}")
            else:
                logger.debug("'nhc_params' not in event data.")
                return

        logger.debug("#### Storing slurmctld_available event relation data in charm StoredState.")
        self._stored.slurmctld_available = True

        # Restart slurmd after we write the event data to their respective locations.
        if self._slurmd.service.active():
            self._slurmd.service.restart()
        else:
            self._slurmd.service.start()

        self._check_status()

    def _on_slurmctld_unavailable(self, _) -> None:
        """Stop slurmd and set slurmctld_available = False when we lose slurmctld."""
        logger.debug("## Slurmctld unavailable")
        self._stored.slurmctld_available = False
        self._stored.nhc_params = ""
        self._stored.auth_key = ""
        self._stored.slurmctld_hosts = ""
        self._slurmd.service.stop()
        self._check_status()

    def _on_slurmd_started(self, _: ServiceStartedEvent) -> None:
        """Handle event emitted by systemd after slurmd daemon successfully starts."""
        self.unit.status = ActiveStatus()

    def _on_slurmd_stopped(self, _: ServiceStoppedEvent) -> None:
        """Handle event emitted by systemd after slurmd daemon is stopped."""
        self.unit.status = BlockedStatus("slurmd not running")

    def _on_node_configured_action(self, _: ActionEvent) -> None:
        """Remove node from DownNodes and mark as active."""
        # Trigger reconfiguration of slurmd node.
        self._new_node = False
        self._slurmctld.set_node()
        self._slurmd.service.restart()
        logger.debug("### This node is not new anymore")

    def _on_show_nhc_config(self, event: ActionEvent) -> None:
        """Show current nhc.conf."""
        try:
            event.set_results({"nhc.conf": nhc.get_config()})
        except FileNotFoundError:
            event.set_results({"nhc.conf": "/etc/nhc/nhc.conf not found."})

    def _on_node_config_action_event(self, event: ActionEvent) -> None:
        """Get or set the user_supplied_node_config.

        Return the node config if the `node-config` parameter is not specified, otherwise
        parse, validate, and store the input of the `node-config` parameter in stored state.
        Lastly, update slurmctld if there are updates to the node config.
        """
        valid_config = True
        config_supplied = False

        if (user_supplied_node_parameters := event.params.get("parameters")) is not None:
            config_supplied = True

            # Parse the user supplied node-config.
            node_parameters_tmp = {}
            try:
                node_parameters_tmp = {
                    item.split("=")[0]: item.split("=")[1]
                    for item in user_supplied_node_parameters.split()
                }
            except IndexError:
                logger.error(
                    "Invalid node parameters specified. Please use KEY1=VAL KEY2=VAL format."
                )
                valid_config = False

            # Validate the user supplied params are valid params.
            for param in node_parameters_tmp:
                if param not in list(NodeOptionSet.keys()):
                    logger.error(f"Invalid user supplied node parameter: {param}.")
                    valid_config = False

            # Validate the user supplied params have valid keys.
            for k, v in node_parameters_tmp.items():
                if v == "":
                    logger.error(f"Invalid user supplied node parameter: {k}={v}.")
                    valid_config = False

            if valid_config:
                if (node_parameters := node_parameters_tmp) != self._user_supplied_node_parameters:
                    self._user_supplied_node_parameters = node_parameters
                    self._slurmctld.set_node()

        results = {
            "node-parameters": " ".join(
                [f"{k}={v}" for k, v in self.get_node()["node_parameters"].items()]
            )
        }

        if config_supplied is True:
            results["user-supplied-node-parameters-accepted"] = f"{valid_config}"

        event.set_results(results)

    @property
    def hostname(self) -> str:
        """Return the hostname."""
        return self._slurmd.hostname

    @property
    def _user_supplied_node_parameters(self) -> dict[Any, Any]:
        """Return the user_supplied_node_parameters from stored state."""
        return self._stored.user_supplied_node_parameters  # type: ignore[return-value]

    @_user_supplied_node_parameters.setter
    def _user_supplied_node_parameters(self, node_parameters: dict) -> None:
        """Set the node_parameters in stored state."""
        self._stored.user_supplied_node_parameters = node_parameters

    @property
    def _new_node(self) -> bool:
        """Get the new_node from stored state."""
        return True if self._stored.new_node is True else False

    @_new_node.setter
    def _new_node(self, new_node: bool) -> None:
        """Set the new_node in stored state."""
        self._stored.new_node = new_node

    def _check_status(self) -> bool:
        """Check if we have all needed components.

        - slurmd installed
        - slurmctld available and working
        """
        if self._stored.slurm_installed is not True:
            self.unit.status = BlockedStatus("Install failed. See `juju debug-log` for details")
            return False

        if self._slurmctld.is_joined is not True:
            self.unit.status = BlockedStatus("Need relations: slurmctld")
            return False

        if self._stored.slurmctld_available is not True:
            self.unit.status = WaitingStatus("Waiting on: slurmctld")
            return False

        return True

    def _reboot_if_required(self, now: bool = False) -> None:
        """Perform a reboot of the unit if required, e.g. following a driver installation."""
        if Path("/var/run/reboot-required").exists():
            logger.info("rebooting unit %s", self.unit.name)
            self.unit.reboot(now)

    def get_node(self) -> Dict[Any, Any]:
        """Get the node from stored state."""
        slurmd_info = machine.get_slurmd_info()

        gres_info = []
        if gpus := gpu.get_all_gpu():
            for model, devices in gpus.items():
                # Build gres.conf line for this GPU model.
                if len(devices) == 1:
                    device_suffix = devices[0]
                else:
                    # Get numeric range of devices associated with this GRES resource. See:
                    # https://slurm.schedmd.com/gres.conf.html#OPT_File
                    device_suffix = calculate_rs(devices)
                gres_line = {
                    "Name": "gpu",
                    "Type": model,
                    "File": f"/dev/nvidia{device_suffix}",
                }
                gres_info.append(gres_line)
                slurmd_info["Gres"] = cast(list[str], slurmd_info.get("Gres", [])) + [
                    f"gpu:{model}:{len(devices)}"
                ]

        real_memory = int(cast(str, slurmd_info["RealMemory"]))

        node = {
            "node_parameters": {
                **slurmd_info,
                "MemSpecLimit": str(min(1024, real_memory // 2)),
                **self._user_supplied_node_parameters,
            },
            "new_node": self._new_node,
            # Do not include GRES configuration if no GPUs detected.
            **({"gres": gres_info} if len(gres_info) > 0 else {}),
        }
        logger.debug(f"Node Configuration: {node}")
        return node

    def get_partition(self) -> Dict[Any, Any]:
        """Return the partition."""
        partition = {
            self.app.name: {**{"State": "UP"}, **self._stored.user_supplied_partition_parameters}
        }  # type: ignore[dict-item]
        logger.debug(f"partition={partition}")
        return partition


if __name__ == "__main__":  # pragma: nocover
    main.main(SlurmdCharm)
