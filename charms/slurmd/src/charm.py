#!/usr/bin/env python3
# Copyright 2020-2024 Omnivector, LLC.
# See LICENSE file for licensing details.

"""Slurmd Operator Charm."""

import logging
import socket
from dataclasses import fields
from typing import Any, Dict

from interface_slurmctld import (
    Slurmctld,
    SlurmctldAvailableEvent,
)
from ops import (
    ActionEvent,
    ActiveStatus,
    BlockedStatus,
    CharmBase,
    ConfigChangedEvent,
    InstallEvent,
    StoredState,
    UpdateStatusEvent,
    WaitingStatus,
    main,
)
from slurm_conf_editor import Node, Partition
from slurmd_ops import SlurmdManager
from utils import slurmd

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
            munge_key=str(),
            new_node=True,
            nhc_conf=str(),
            nhc_params=str(),
            slurm_installed=False,
            slurmctld_available=False,
            slurmctld_host=str(),
            user_supplied_node_parameters={},
            user_supplied_partition_parameters={},
        )

        self._slurmd_manager = SlurmdManager()
        self._slurmctld = Slurmctld(self, "slurmctld")
        self._systemd_notices = SystemdNotices(self, ["slurmd"])

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
        self.unit.status = WaitingStatus("Installing slurmd")

        if self._slurmd_manager.install():
            self.unit.set_workload_version(self._slurmd_manager.version())
            slurmd.override_service()
            self._systemd_notices.subscribe()

            self._stored.slurm_installed = True
        else:
            self.unit.status = BlockedStatus("Error installing slurmd")
            event.defer()

        self._check_status()

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Handle charm configuration changes."""
        if nhc_conf := self.model.config.get("nhc-conf"):
            if nhc_conf != self._stored.nhc_conf:
                self._stored.nhc_conf = nhc_conf
                self._slurmd_manager.render_nhc_config(nhc_conf)

        user_supplied_partition_parameters = self.model.config.get("partition-config")

        if self.model.unit.is_leader():
            if user_supplied_partition_parameters is not None:
                tmp_params = {}
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
                    if parameter not in [
                        partition_parameter.name for partition_parameter in fields(Partition)
                    ]:
                        logger.error(
                            f"Invalid user supplied partition configuration parameter: {parameter}."
                        )
                        return

                self._stored.user_supplied_partition_parameters = tmp_params

                if self._slurmctld.is_joined:
                    self._slurmctld.set_partition()

    def _on_update_status(self, event: UpdateStatusEvent) -> None:
        """Handle update status."""
        self._check_status()

    def _on_slurmctld_available(self, event: SlurmctldAvailableEvent) -> None:
        """Retrieve the slurmctld_available event data and store in charm state."""
        if self._stored.slurm_installed is not True:
            event.defer()
            return

        if (slurmctld_host := event.slurmctld_host) != self._stored.slurmctld_host:
            if slurmctld_host is not None:
                slurmd.override_default(slurmctld_host)
                self._stored.slurmctld_host = slurmctld_host
                logger.debug(f"slurmctld_host={slurmctld_host}")
            else:
                logger.debug("'slurmctld_host' not in event data.")
                return

        if (munge_key := event.munge_key) != self._stored.munge_key:
            if munge_key is not None:
                self._stored.munge_key = munge_key
                self._slurmd_manager.write_munge_key(munge_key)
                logger.debug(f"munge_key={munge_key}")
            else:
                logger.debug("'munge_key' not in event data.")
                return

        if (nhc_params := event.nhc_params) != self._stored.nhc_params:
            if nhc_params is not None:
                self._stored.nhc_params = nhc_params
                self._slurmd_manager.render_nhc_wrapper(nhc_params)
                logger.debug(f"nhc_params={nhc_params}")
            else:
                logger.debug("'nhc_params' not in event data.")
                return

        logger.debug(
            "#### Storing slurmctld_available event relation data in charm StoredState." ""
        )
        self._stored.slurmctld_available = True

        # Restart munged and slurmd after we write the event data to their respective locations.
        if self._slurmd_manager.restart_munged():
            logger.debug("## Munge restarted successfully")
        else:
            logger.error("## Unable to restart munge")

        slurmd.restart()
        self._check_status()

    def _on_slurmctld_unavailable(self, event) -> None:
        """Stop slurmd and set slurmctld_available = False when we lose slurmctld."""
        logger.debug("## Slurmctld unavailable")
        self._stored.slurmctld_available = False
        self._stored.nhc_params = ""
        self._stored.munge_key = ""
        self._stored.slurmctld_host = ""
        slurmd.stop()
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
        slurmd.restart()
        logger.debug("### This node is not new anymore")

    def _on_show_nhc_config(self, event: ActionEvent) -> None:
        """Show current nhc.conf."""
        nhc_conf = self._slurmd_manager.get_nhc_config()
        event.set_results({"nhc.conf": nhc_conf})

    def _on_node_config_action_event(self, event: ActionEvent) -> None:
        """Get or set the user_supplied_node_conifg.

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
                if param not in [node_param.name for node_param in fields(Node)]:
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
        return socket.gethostname().split(".")[0]

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
        - munge key configured and working
        """
        if self._stored.slurm_installed is not True:
            self.unit.status = BlockedStatus("Error installing slurmd")
            return False

        if self._slurmctld.is_joined is not True:
            self.unit.status = BlockedStatus("Need relations: slurmctld")
            return False

        if self._stored.slurmctld_available is not True:
            self.unit.status = WaitingStatus("Waiting on: slurmctld")
            return False

        if not self._slurmd_manager.check_munged():
            self.unit.status = BlockedStatus("Error configuring munge key")
            return False

        return True

    def get_node(self) -> Dict[Any, Any]:
        """Get the node from stored state."""
        node = {
            "node_parameters": {
                **self._slurmd_manager.get_node_config(),
                **self._user_supplied_node_parameters,
            },
            "new_node": self._new_node,
        }
        logger.debug(f"Node Configuration: {node}")
        return node

    def get_partition(self) -> Dict[Any, Any]:
        """Return the partition."""
        partition = {self.app.name: {**{"State": "UP"}, **self._stored.user_supplied_partition_parameters}}  # type: ignore[dict-item]
        logger.debug(f"partition={partition}")
        return partition


if __name__ == "__main__":  # pragma: nocover
    main.main(SlurmdCharm)
