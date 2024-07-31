#!/usr/bin/env python3
# Copyright 2020 Omnivector Solutions, LLC
# See LICENSE file for licensing details.

"""SlurmctldCharm."""

import logging
import shlex
import subprocess
from typing import Any, Dict, List, Optional, Union

from constants import CHARM_MAINTAINED_SLURM_CONF_PARAMETERS, SLURM_CONF_PATH
from interface_slurmd import (
    PartitionAvailableEvent,
    PartitionUnavailableEvent,
    Slurmd,
    SlurmdAvailableEvent,
    SlurmdDepartedEvent,
)
from interface_slurmdbd import (
    Slurmdbd,
    SlurmdbdAvailableEvent,
    SlurmdbdUnavailableEvent,
)
from interface_slurmrestd import (
    Slurmrestd,
    SlurmrestdAvailableEvent,
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
from slurm_conf_editor import slurm_conf_as_string
from slurmctld_ops import SlurmctldManager, is_container

logger = logging.getLogger()


class SlurmctldCharm(CharmBase):
    """Slurmctld lifecycle events."""

    _stored = StoredState()

    def __init__(self, *args):
        """Init _stored attributes and interfaces, observe events."""
        super().__init__(*args)

        self._stored.set_default(
            default_partition=str(),
            jwt_key=str(),
            munge_key=str(),
            new_nodes=[],
            nhc_params=str(),
            slurm_installed=False,
            slurmdbd_host=str(),
            user_supplied_slurm_conf_params=str(),
        )

        self._slurmctld_manager = SlurmctldManager()

        self._slurmd = Slurmd(self, "slurmd")
        self._slurmdbd = Slurmdbd(self, "slurmdbd")
        self._slurmrestd = Slurmrestd(self, "slurmrestd")

        event_handler_bindings = {
            self.on.install: self._on_install,
            self.on.update_status: self._on_update_status,
            self.on.config_changed: self._on_config_changed,
            self._slurmdbd.on.slurmdbd_available: self._on_slurmdbd_available,
            self._slurmdbd.on.slurmdbd_unavailable: self._on_slurmdbd_unavailable,
            self._slurmd.on.partition_available: self._on_write_slurm_conf,
            self._slurmd.on.partition_unavailable: self._on_write_slurm_conf,
            self._slurmd.on.slurmd_available: self._on_write_slurm_conf,
            self._slurmd.on.slurmd_departed: self._on_write_slurm_conf,
            self._slurmrestd.on.slurmrestd_available: self._on_slurmrestd_available,
            self.on.show_current_config_action: self._on_show_current_config_action,
            self.on.drain_action: self._on_drain_nodes_action,
            self.on.resume_action: self._on_resume_nodes_action,
        }
        for event, handler in event_handler_bindings.items():
            self.framework.observe(event, handler)

    def _on_install(self, event: InstallEvent) -> None:
        """Perform installation operations for slurmctld."""
        self.unit.status = WaitingStatus("Installing slurmctld")

        if self._slurmctld_manager.install():

            # Store the munge_key and jwt_rsa key in the stored state.
            # NOTE: Use secrets instead of stored state when secrets are supported the framework.
            if self.model.unit.is_leader():
                jwt_rsa = self._slurmctld_manager.generate_jwt_rsa()
                self._stored.jwt_rsa = jwt_rsa

                munge_key = self._slurmctld_manager.generate_munge_key()
                self._stored.munge_key = munge_key

                self._slurmctld_manager.stop_munged()
                self._slurmctld_manager.write_munge_key(munge_key)
                self._slurmctld_manager.start_munged()

                self._slurmctld_manager.stop_slurmctld()
                self._slurmctld_manager.write_jwt_rsa(jwt_rsa)
                self._slurmctld_manager.start_slurmctld()

                self.unit.set_workload_version(self._slurmctld_manager.version())
                self.slurm_installed = True
            else:
                self.unit.status = BlockedStatus("Only singleton slurmctld is supported.")
                logger.debug("Secondary slurmctld not supported.")
                event.defer()
        else:
            self.unit.status = BlockedStatus("Error installing slurmctld")
            logger.error("Cannot install slurmctld, please debug.")
            event.defer()

        self._on_write_slurm_conf(event)

    def _on_config_changed(self, event: ConfigChangedEvent) -> None:
        """Perform config-changed operations."""
        charm_config_nhc_params = str(self.config.get("health-check-params", ""))
        if (charm_config_nhc_params != self._stored.nhc_params) and (
            charm_config_nhc_params != ""
        ):
            logger.debug("## NHC user supplied params changed, sending to slurmd.")
            self._stored.nhc_params = charm_config_nhc_params
            # Send the custom NHC parameters to all slurmd.
            self._slurmd.set_nhc_params(charm_config_nhc_params)

        write_slurm_conf = False
        if charm_config_default_partition := self.config.get("default-partition"):
            if charm_config_default_partition != self._stored.default_partition:
                logger.debug("## Default partition configuration changed.")
                self._stored.default_partition = charm_config_default_partition
                write_slurm_conf = True

        if (
            charm_config_slurm_conf_params := self.config.get("slurm-conf-parameters")
        ) is not None:
            if charm_config_slurm_conf_params != self._stored.user_supplied_slurm_conf_params:
                logger.debug("## User supplied parameters changed.")
                self._stored.user_supplied_slurm_conf_params = charm_config_slurm_conf_params
                write_slurm_conf = True

        if write_slurm_conf:
            logger.debug("## Emitting write-slurm-config event.")
            self._on_write_slurm_conf(event)

    def _on_update_status(self, event: UpdateStatusEvent) -> None:
        """Handle update status."""
        self._check_status()

    def _on_show_current_config_action(self, event: ActionEvent) -> None:
        """Show current slurm.conf."""
        slurm_conf = SLURM_CONF_PATH.read_text()
        event.set_results({"slurm.conf": slurm_conf})

    def _on_slurmrestd_available(self, event: SlurmrestdAvailableEvent) -> None:
        """Check that we have slurm_config when slurmrestd available otherwise defer the event."""
        if self.model.unit.is_leader():
            if self._check_status():
                slurm_conf = slurm_conf_as_string(self._assemble_slurm_conf())
                self._slurmrestd.set_slurm_config_on_app_relation_data(slurm_conf)
                return
            logger.debug("Cluster not ready yet, deferring event.")
            event.defer()

    def _on_slurmdbd_available(self, event: SlurmdbdAvailableEvent) -> None:
        self._stored.slurmdbd_host = event.slurmdbd_host
        self._on_write_slurm_conf(event)

    def _on_slurmdbd_unavailable(self, event: SlurmdbdUnavailableEvent) -> None:
        self._stored.slurmdbd_host = ""
        self._check_status()

    def _on_drain_nodes_action(self, event: ActionEvent) -> None:
        """Drain specified nodes."""
        nodes = event.params["nodename"]
        reason = event.params["reason"]

        logger.debug(f"#### Draining {nodes} because {reason}.")
        event.log(f"Draining {nodes} because {reason}.")

        try:
            cmd = f'scontrol update nodename={nodes} state=drain reason="{reason}"'
            subprocess.check_output(shlex.split(cmd))
            event.set_results({"status": "draining", "nodes": nodes})
        except subprocess.CalledProcessError as e:
            event.fail(message=f"Error draining {nodes}: {e.output}")

    def _on_resume_nodes_action(self, event: ActionEvent) -> None:
        """Resume specified nodes."""
        nodes = event.params["nodename"]

        logger.debug(f"#### Resuming {nodes}.")
        event.log(f"Resuming {nodes}.")

        try:
            cmd = f"scontrol update nodename={nodes} state=resume"
            subprocess.check_output(shlex.split(cmd))
            event.set_results({"status": "resuming", "nodes": nodes})
        except subprocess.CalledProcessError as e:
            event.fail(message=f"Error resuming {nodes}: {e.output}")

    def _on_write_slurm_conf(
        self,
        event: Union[
            ConfigChangedEvent,
            InstallEvent,
            SlurmdbdAvailableEvent,
            SlurmdDepartedEvent,
            SlurmdAvailableEvent,
            PartitionUnavailableEvent,
            PartitionAvailableEvent,
        ],
    ) -> None:
        """Check that we have what we need before we proceed."""
        logger.debug("### Slurmctld - _on_write_slurm_conf()")

        # only the leader should write the config, restart, and scontrol reconf
        if not self.model.unit.is_leader():
            return

        if not self._check_status():
            event.defer()
            return

        if slurm_config := self._assemble_slurm_conf():
            self._slurmctld_manager.stop_slurmctld()
            self._slurmctld_manager.write_slurm_conf(slurm_config)

            # Write out any user_supplied_cgroup_parameters to /etc/slurm/cgroup.conf.
            if user_supplied_cgroup_parameters := self.config.get("cgroup-parameters", ""):
                self._slurmctld_manager.write_cgroup_conf(str(user_supplied_cgroup_parameters))

            self._slurmctld_manager.start_slurmctld()

            self._slurmctld_manager.slurm_cmd("scontrol", "reconfigure")

            # Transitioning Nodes
            #
            # 1) Identify transitioning_nodes by comparing the new_nodes in StoredState with the
            #    new_nodes that come from slurmd relation data.
            #
            # 2) If there are transitioning_nodes, resume them, and update the new_nodes in
            #    StoredState.
            new_nodes_from_stored_state = self.new_nodes
            new_nodes_from_slurm_config = self._get_new_node_names_from_slurm_config(slurm_config)

            transitioning_nodes: list = [
                node
                for node in new_nodes_from_stored_state
                if node not in new_nodes_from_slurm_config
            ]

            if len(transitioning_nodes) > 0:
                self._resume_nodes(transitioning_nodes)
                self.new_nodes = new_nodes_from_slurm_config.copy()

            # slurmrestd needs the slurm.conf file, so send it every time it changes.
            if self._slurmrestd.is_joined is not False:
                slurm_conf = slurm_conf_as_string(slurm_config)
                self._slurmrestd.set_slurm_config_on_app_relation_data(slurm_conf)
        else:
            logger.debug("## Should write slurm.conf, but we don't have it. " "Deferring.")
            event.defer()

    def _assemble_slurm_conf(self) -> Dict[str, Any]:
        """Return the slurm.conf parameters."""
        user_supplied_parameters = self._get_user_supplied_parameters()

        slurmd_parameters = self._slurmd.get_new_nodes_and_nodes_and_partitions()

        def _assemble_slurmctld_parameters() -> str:
            # Preprocess merging slurmctld_parameters if they exist in the context
            slurmctld_param_config = CHARM_MAINTAINED_SLURM_CONF_PARAMETERS[
                "SlurmctldParameters"
            ].split(",")
            user_config = []

            if (
                user_supplied_slurmctld_parameters := user_supplied_parameters.get(
                    "SlurmctldParameters", ""
                )
                != ""
            ):
                user_config.extend(user_supplied_slurmctld_parameters.split(","))

            return ",".join(slurmctld_param_config + user_config)

        accounting_params = {}
        if (slurmdbd_host := self._stored.slurmdbd_host) != "":
            accounting_params = {
                "AccountingStorageHost": slurmdbd_host,
                "AccountingStorageType": "accounting_storage/slurmdbd",
                "AccountingStoragePass": "/var/run/munge/munge.socket.2",
                "AccountingStoragePort": "6819",
            }

        slurm_conf = {
            "ClusterName": self.cluster_name,
            "SlurmctldAddr": self._slurmd_ingress_address,
            "SlurmctldHost": self.hostname,
            "SlurmctldParameters": _assemble_slurmctld_parameters(),
            "ProctrackType": "proctrack/linuxproc" if is_container() else "proctrack/cgroup",
            **accounting_params,
            **CHARM_MAINTAINED_SLURM_CONF_PARAMETERS,
            **slurmd_parameters,
            **user_supplied_parameters,
        }

        logger.debug(f"slurm.conf: {slurm_conf}")
        return slurm_conf

    def _get_user_supplied_parameters(self) -> Dict[Any, Any]:
        """Gather, parse, and return the user supplied parameters."""
        user_supplied_parameters = {}
        if custom_config := self.config.get("slurm-conf-parameters"):
            user_supplied_parameters = {
                line.split("=")[0]: line.split("=")[1]
                for line in str(custom_config).split("\n")
                if not line.startswith("#") and line.strip() != ""
            }
        return user_supplied_parameters

    def _get_new_node_names_from_slurm_config(
        self, slurm_config: Dict[str, Any]
    ) -> List[Optional[str]]:
        """Given the slurm_config, return the nodes that are DownNodes with reason 'New node.'."""
        new_node_names = []
        if down_nodes_from_slurm_config := slurm_config.get("down_nodes"):
            for down_nodes_entry in down_nodes_from_slurm_config:
                for down_node_name in down_nodes_entry["DownNodes"]:
                    if down_nodes_entry["Reason"] == "New node.":
                        new_node_names.append(down_node_name)
        return new_node_names

    def _check_status(self) -> bool:  # noqa C901
        """Check for all relations and set appropriate status.

        This charm needs these conditions to be satisfied in order to be ready:
        - Slurmctld component installed
        - Munge running
        """
        if self.slurm_installed is not True:
            self.unit.status = BlockedStatus("Error installing slurmctld")
            return False

        if not self._slurmctld_manager.check_munged():
            self.unit.status = BlockedStatus("Error configuring munge key")
            return False

        self.unit.status = ActiveStatus("")
        return True

    def get_munge_key(self) -> Optional[str]:
        """Get the stored munge key."""
        return str(self._stored.munge_key)

    def get_jwt_rsa(self) -> Optional[str]:
        """Get the stored jwt_rsa key."""
        return str(self._stored.jwt_rsa)

    def _resume_nodes(self, nodelist: List[str]) -> None:
        """Run scontrol to resume the specified node list."""
        nodes = ",".join(nodelist)
        update_cmd = f"update nodename={nodes} state=resume"
        self._slurmctld_manager.slurm_cmd("scontrol", update_cmd)

    @property
    def cluster_name(self) -> str:
        """Return the cluster name."""
        cluster_name = "charmedhpc"
        if cluster_name_from_config := self.config.get("cluster-name"):
            cluster_name = str(cluster_name_from_config)
        return cluster_name

    @property
    def new_nodes(self) -> list:
        """Return new_nodes from StoredState.

        Note: Ignore the attr-defined for now until this is fixed upstream.
        """
        return list(self._stored.new_nodes)  # type: ignore[call-overload]

    @new_nodes.setter
    def new_nodes(self, new_nodes: List[Any]) -> None:
        """Set the new nodes."""
        self._stored.new_nodes = new_nodes

    @property
    def hostname(self) -> str:
        """Return the hostname."""
        return self._slurmctld_manager.hostname

    @property
    def _slurmd_ingress_address(self) -> str:
        """Return the ingress_address from the slurmd relation if it exists."""
        ingress_address = ""
        if binding := self.model.get_binding("slurmd"):
            ingress_address = f"{binding.network.ingress_address}"
        return ingress_address

    @property
    def slurm_installed(self) -> bool:
        """Return slurm_installed from stored state."""
        return True if self._stored.slurm_installed is True else False

    @slurm_installed.setter
    def slurm_installed(self, slurm_installed: bool) -> None:
        """Set slurm_installed in stored state."""
        self._stored.slurm_installed = slurm_installed


if __name__ == "__main__":
    main.main(SlurmctldCharm)
