#!/usr/bin/env python3
# Copyright 2020-2025 Omnivector, LLC
# See LICENSE file for licensing details.

"""SlurmctldCharm."""

import logging
import secrets
import shlex
import subprocess
from typing import Any, Dict, List, Optional, Union

from constants import (
    CHARM_MAINTAINED_CGROUP_CONF_PARAMETERS,
    CHARM_MAINTAINED_SLURM_CONF_PARAMETERS,
    CLUSTER_NAME_PREFIX,
    PEER_INTEGRATION_NAME,
    PROMETHEUS_EXPORTER_PORT,
    SLURMCTLD_PORT,
)
from exceptions import IngressAddressUnavailableError
from hpc_libs.is_container import is_container
from integrations import SlurmctldPeer, SlurmctldPeerConnectedEvent
from interface_influxdb import InfluxDB, InfluxDBAvailableEvent, InfluxDBUnavailableEvent
from interface_sackd import Sackd
from interface_slurmd import (
    PartitionAvailableEvent,
    PartitionUnavailableEvent,
    Slurmd,
    SlurmdAvailableEvent,
    SlurmdDepartedEvent,
)
from interface_slurmdbd import Slurmdbd, SlurmdbdAvailableEvent, SlurmdbdUnavailableEvent
from interface_slurmrestd import Slurmrestd, SlurmrestdAvailableEvent
from netifaces import interfaces
from ops import (
    ActionEvent,
    ActiveStatus,
    BlockedStatus,
    CharmBase,
    ConfigChangedEvent,
    InstallEvent,
    StartEvent,
    StoredState,
    UpdateStatusEvent,
    WaitingStatus,
    main,
)
from slurm_ops import SlurmctldManager, SlurmOpsError, scontrol
from slurmutils import AcctGatherConfig, CGroupConfig, SlurmConfig

from charms.grafana_agent.v0.cos_agent import COSAgentProvider

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
            auth_key=str(),
            new_nodes=[],
            nhc_params=str(),
            slurm_installed=False,
            slurmdbd_host=str(),
            user_supplied_slurm_conf_params=str(),
            acct_gather_params={},
            job_profiling_slurm_conf={},
        )

        self._slurmctld = SlurmctldManager(snap=False)
        self._slurmctld_peer = SlurmctldPeer(self, PEER_INTEGRATION_NAME)
        self._sackd = Sackd(self, "login-node")
        self._slurmd = Slurmd(self, "slurmd")
        self._slurmdbd = Slurmdbd(self, "slurmdbd")
        self._slurmrestd = Slurmrestd(self, "slurmrestd")
        self._grafana_agent = COSAgentProvider(
            self,
            metrics_endpoints=[{"path": "/metrics", "port": 9092}],
            metrics_rules_dir="./src/cos/alert_rules/prometheus",
            dashboard_dirs=["./src/cos/grafana_dashboards"],
            recurse_rules_dirs=True,
        )
        self._influxdb = InfluxDB(self, "influxdb")

        event_handler_bindings = {
            self.on.install: self._on_install,
            self.on.start: self._on_start,
            self.on.update_status: self._on_update_status,
            self.on.config_changed: self._on_config_changed,
            self._slurmctld_peer.on.slurmctld_peer_connected: self._on_slurmctld_peer_connected,
            self._slurmdbd.on.slurmdbd_available: self._on_slurmdbd_available,
            self._slurmdbd.on.slurmdbd_unavailable: self._on_slurmdbd_unavailable,
            self._slurmd.on.partition_available: self._on_write_slurm_conf,
            self._slurmd.on.partition_unavailable: self._on_write_slurm_conf,
            self._slurmd.on.slurmd_available: self._on_slurmd_available,
            self._slurmd.on.slurmd_departed: self._on_slurmd_departed,
            self._slurmrestd.on.slurmrestd_available: self._on_slurmrestd_available,
            self._influxdb._on.influxdb_available: self._on_influxdb_available,
            self._influxdb._on.influxdb_unavailable: self._on_influxdb_unavailable,
            self.on.show_current_config_action: self._on_show_current_config_action,
            self.on.drain_action: self._on_drain_nodes_action,
            self.on.resume_action: self._on_resume_nodes_action,
        }
        for event, handler in event_handler_bindings.items():
            self.framework.observe(event, handler)

    def _on_install(self, event: InstallEvent) -> None:
        """Perform installation operations for slurmctld."""
        self.unit.status = WaitingStatus("installing slurmctld")
        try:
            if self.unit.is_leader():
                self._slurmctld.install()

                # TODO: https://github.com/charmed-hpc/slurm-charms/issues/38 -
                #  Use Juju Secrets instead of StoredState for exchanging keys between units.
                self._slurmctld.jwt.generate()
                self._stored.jwt_rsa = self._slurmctld.jwt.get()

                self._slurmctld.key.generate()
                self._stored.auth_key = self._slurmctld.key.get()

                self._slurmctld.service.enable()

                self._slurmctld.exporter.args = [
                    "-slurm.collect-diags",
                    "-slurm.collect-limits",
                ]
                self._slurmctld.exporter.service.enable()
                self._slurmctld.exporter.service.restart()

                self.unit.set_workload_version(self._slurmctld.version())

                self.slurm_installed = True
            else:
                self.unit.status = BlockedStatus("slurmctld high-availability not supported")
                logger.warning(
                    "slurmctld high-availability is not supported yet. please scale down application."
                )
                event.defer()
        except SlurmOpsError as e:
            logger.error(e.message)
            event.defer()

        self.unit.open_port("tcp", SLURMCTLD_PORT)
        self.unit.open_port("tcp", PROMETHEUS_EXPORTER_PORT)

    def _on_start(self, event: StartEvent) -> None:
        """Write slurm.conf and start `slurmctld` service.

        Notes:
            - The start hook can execute multiple times in a charms lifecycle,
              for example, after a reboot of the underlying instance.
        """
        if self.unit.is_leader():
            self._on_write_slurm_conf(event)
            if event.deferred:
                logger.debug("attempt to write slurm.conf deferred event")
                return

            if not self._check_status():
                logger.debug("unit not ready. deferring event")
                event.defer()
                return

            try:
                self._slurmctld.service.enable()
                self._slurmctld.service.start()
                self._slurmctld.exporter.service.enable()
                self._slurmctld.exporter.service.restart()
            except SlurmOpsError as e:
                logger.error(e.message)
                event.defer()
        else:
            msg = "High availability of slurmctld is not supported at this time."
            self.unit.status = BlockedStatus(msg)
            logger.warning(msg)
            event.defer()

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

    def _on_update_status(self, _: UpdateStatusEvent) -> None:
        """Handle update status."""
        self._check_status()

    def _on_show_current_config_action(self, event: ActionEvent) -> None:
        """Show current slurm.conf."""
        event.set_results({"slurm.conf": str(self._slurmctld.config.load())})

    def _on_slurmctld_peer_connected(self, _: SlurmctldPeerConnectedEvent) -> None:
        """Handle when `slurmctld` peer integration is created."""
        self._slurmctld_peer.cluster_name = (
            cluster_name
            if (cluster_name := self.config.get("cluster-name", "")) != ""
            else f"{CLUSTER_NAME_PREFIX}-{secrets.token_urlsafe(3)}"
        )

    def _on_slurmrestd_available(self, event: SlurmrestdAvailableEvent) -> None:
        """Check that we have slurm_config when slurmrestd available otherwise defer the event."""
        if self.unit.is_leader():
            if self._check_status():
                if self._stored.slurmdbd_host != "":
                    self._slurmrestd.set_slurm_config_on_app_relation_data(
                        str(self._slurmctld.config.load()),
                    )
                    return
                else:
                    logger.debug("Need slurmdbd for slurmrestd relation.")
                    event.defer()
                    return
            else:
                logger.debug("Cluster not ready yet, deferring event.")
                event.defer()

    def _on_slurmdbd_available(self, event: SlurmdbdAvailableEvent) -> None:
        self._stored.slurmdbd_host = event.slurmdbd_host
        self._on_write_slurm_conf(event)

    def _on_slurmdbd_unavailable(self, event: SlurmdbdUnavailableEvent) -> None:
        self._stored.slurmdbd_host = ""
        self._on_write_slurm_conf(event)

    def _on_influxdb_available(self, event: InfluxDBAvailableEvent) -> None:
        """Assemble the influxdb acct_gather.conf options."""
        logger.debug("## Generating acct gather configuration")

        acct_gather_params = {
            "profileinfluxdbdefault": ["all"],
            "profileinfluxdbhost": event.influxdb_host,
            "profileinfluxdbuser": event.influxdb_user,
            "profileinfluxdbpass": event.influxdb_pass,
            "profileinfluxdbdatabase": event.influxdb_database,
            "profileinfluxdbrtpolicy": event.influxdb_policy,
            "sysfsinterfaces": interfaces(),
        }
        logger.debug(f"## _stored.acct_gather_params: {acct_gather_params}")
        self._stored.acct_gather_params = acct_gather_params

        self._stored.job_profiling_slurm_conf = {
            "acctgatherprofiletype": "acct_gather_profile/influxdb",
            "acctgatherinterconnecttype": "acct_gather_interconnect/sysfs",
            "accountingstoragetres": ["ic/sysfs"],
            "acctgathernodefreq": 30,
            "jobacctgatherfrequency": {"task": 5, "network": 5},
            "jobacctgathertype": (
                "jobacct_gather/linux" if is_container() else "jobacct_gather/cgroup"
            ),
        }
        logger.debug(f"## SlurmConfProfilingData: {self._stored.job_profiling_slurm_conf}")
        self._on_write_slurm_conf(event)

    def _on_influxdb_unavailable(self, event: InfluxDBUnavailableEvent) -> None:
        """Clear the acct_gather.conf options on departed relation."""
        logger.debug("## Clearing acct_gather configuration")

        self._stored.acct_gather_params = {}
        self._stored.job_profiling_slurm_conf = {}
        self._on_write_slurm_conf(event)

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
            cmd = f"scontrol update nodename={nodes} state=idle"
            subprocess.check_output(shlex.split(cmd))
            event.set_results({"status": "resuming", "nodes": nodes})
        except subprocess.CalledProcessError as e:
            event.fail(message=f"Error resuming {nodes}: {e.output}")

    def _on_slurmd_available(self, event: SlurmdAvailableEvent) -> None:
        """Triggers when a slurmd unit joins the relation."""
        self._on_write_slurm_conf(event)

    def _on_slurmd_departed(self, event: SlurmdDepartedEvent) -> None:
        """Triggers when a slurmd unit departs the relation.

        Notes:
            Lack of map between departing unit and NodeName complicates removal of node from gres.conf.
            Instead, rewrite full gres.conf with data from remaining units.
        """
        # Reconcile the new_nodes.
        new_nodes = self.new_nodes
        logger.debug(f"New nodes from stored state: {new_nodes}")

        active_nodes = self._slurmd.get_active_nodes()
        logger.debug(f"Active nodes: {active_nodes}")

        for node in new_nodes:
            if node not in active_nodes:
                logger.debug(f"Removing node: {node}")
                new_nodes.remove(node)

        # Set the remaining new nodes
        self.new_nodes = new_nodes
        self._on_write_slurm_conf(event)

    def _assemble_acct_gather_config(self) -> Optional[AcctGatherConfig]:
        """Assemble and return the AcctGatherConfig."""
        if (acct_gather_stored_params := self._stored.acct_gather_params) != {}:
            return AcctGatherConfig(
                profileinfluxdbdefault=list(acct_gather_stored_params["profileinfluxdbdefault"]),
                profileinfluxdbhost=acct_gather_stored_params["profileinfluxdbhost"],
                profileinfluxdbuser=acct_gather_stored_params["profileinfluxdbuser"],
                profileinfluxdbpass=acct_gather_stored_params["profileinfluxdbpass"],
                profileinfluxdbdatabase=acct_gather_stored_params["profileinfluxdbdatabase"],
                profileinfluxdbrtpolicy=acct_gather_stored_params["profileinfluxdbrtpolicy"],
                sysfsinterfaces=list(acct_gather_stored_params["sysfsinterfaces"]),
            )
        return None

    def _on_write_slurm_conf(
        self,
        event: Union[
            ConfigChangedEvent,
            InfluxDBAvailableEvent,
            InfluxDBUnavailableEvent,
            StartEvent,
            SlurmdbdAvailableEvent,
            SlurmdbdUnavailableEvent,
            SlurmdDepartedEvent,
            SlurmdAvailableEvent,
            PartitionUnavailableEvent,
            PartitionAvailableEvent,
        ],
    ) -> None:
        """Check that we have what we need before we proceed."""
        logger.debug("### Slurmctld - _on_write_slurm_conf()")

        # Only the leader should write the config, restart, and scontrol reconf.
        if not self.unit.is_leader():
            return

        # If slurmctld isn't installed and we don't have a cluster_name, defer.
        if not self._check_status():
            event.defer()
            return

        if slurm_config := self._assemble_slurm_conf():
            self._slurmctld.service.stop()

            logger.debug(f"Writing slurm.conf: {slurm_config}")
            self._slurmctld.config.dump(slurm_config)

            self._slurmctld.acct_gather.path.unlink(missing_ok=True)
            # Slurmdbd is required to use profiling, so check for it here.
            if self._stored.slurmdbd_host != "":
                if (acct_gather_config := self._assemble_acct_gather_config()) is not None:
                    logger.debug(f"Writing acct_gather.conf: {acct_gather_config}")
                    self._slurmctld.acct_gather.dump(acct_gather_config)

            # Write out any cgroup parameters to /etc/slurm/cgroup.conf.
            if not is_container():
                cgroup_config = CHARM_MAINTAINED_CGROUP_CONF_PARAMETERS
                if user_supplied_cgroup_params := self._get_user_supplied_cgroup_parameters():
                    cgroup_config.update(user_supplied_cgroup_params)
                self._slurmctld.cgroup.dump(CGroupConfig(**cgroup_config))

            self._slurmctld.service.start()

            try:
                scontrol("reconfigure")
            except SlurmOpsError as e:
                logger.error(e)
                return

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
            if self._slurmrestd.is_joined is not False and self._stored.slurmdbd_host != "":
                self._slurmrestd.set_slurm_config_on_app_relation_data(str(slurm_config))
        else:
            logger.debug("## Should write slurm.conf, but we don't have it. Deferring.")
            event.defer()

    def _assemble_profiling_params(self) -> Dict[Any, Any]:
        """Assemble and return the profiling parameters."""
        job_profiling_slurm_conf_parameters = {}
        if (profiling_params := self._stored.job_profiling_slurm_conf) != {}:
            for k, v in profiling_params.items():
                if k == "accountingstoragetres":
                    v = list(v)
                if k == "jobacctgatherfrequency":
                    v = dict(v)
                job_profiling_slurm_conf_parameters[k] = v
        return job_profiling_slurm_conf_parameters

    def _assemble_slurm_conf(self) -> SlurmConfig:
        """Return the slurm.conf parameters."""
        user_supplied_parameters = self._get_user_supplied_parameters()
        slurmd_parameters = self._slurmd.get_new_nodes_and_nodes_and_partitions()

        def _assemble_slurmctld_parameters() -> dict[str, Any]:
            # Preprocess merging slurmctld_parameters if they exist in the context
            slurmctld_parameters = {"enable_configless": True}

            if (
                user_supplied_slurmctld_parameters := user_supplied_parameters.get(
                    "slurmctldparameters", ""
                )
                != ""
            ):
                for opt in user_supplied_slurmctld_parameters.split(","):
                    k, v = opt.split("=", maxsplit=1)
                    slurmctld_parameters.update({k: v})

            return slurmctld_parameters

        accounting_params = {}
        profiling_parameters = {}
        if (slurmdbd_host := self._stored.slurmdbd_host) != "":
            accounting_params = {
                "accountingstoragehost": slurmdbd_host,
                "accountingstoragetype": "accounting_storage/slurmdbd",
                "accountingstorageport": 6819,
            }
            # Need slurmdbd configured to use profiling
            profiling_parameters = self._assemble_profiling_params()
            logger.debug(f"## profiling_params: {profiling_parameters}")

        slurm_conf = SlurmConfig.from_dict(
            {
                "clustername": self.cluster_name,
                "slurmctldaddr": self._ingress_address,
                "slurmctldhost": [self._slurmctld.hostname],
                "slurmctldparameters": _assemble_slurmctld_parameters(),
                "proctracktype": "proctrack/linuxproc" if is_container() else "proctrack/cgroup",
                "taskplugin": (
                    ["task/affinity"] if is_container() else ["task/cgroup", "task/affinity"]
                ),
                **profiling_parameters,
                **accounting_params,
                **CHARM_MAINTAINED_SLURM_CONF_PARAMETERS,
                **slurmd_parameters,
                **user_supplied_parameters,
            }
        )
        logger.debug(f"slurm.conf: {slurm_conf.dict()}")
        return slurm_conf

    def _get_user_supplied_parameters(self) -> Dict[Any, Any]:
        """Gather, parse, and return the user supplied parameters."""
        user_supplied_parameters = {}
        if custom_config := self.config.get("slurm-conf-parameters"):
            user_supplied_parameters = {
                line.split("=")[0]: line.split("=", 1)[1]
                for line in str(custom_config).split("\n")
                if not line.startswith("#") and line.strip() != ""
            }
        return user_supplied_parameters

    def _get_user_supplied_cgroup_parameters(self) -> Dict[Any, Any]:
        """Gather, parse, and return the user supplied cgroup parameters."""
        user_supplied_cgroup_parameters = {}
        if custom_cgroup_config := self.config.get("cgroup-parameters"):
            user_supplied_cgroup_parameters = {
                line.split("=")[0]: line.split("=", 1)[1]
                for line in str(custom_cgroup_config).split("\n")
                if not line.startswith("#") and line.strip() != ""
            }
        return user_supplied_cgroup_parameters

    def _get_new_node_names_from_slurm_config(
        self, slurm_config: SlurmConfig
    ) -> List[Optional[str]]:
        """Given the slurm_config, return the nodes that are DownNodes with reason 'New node.'."""
        new_node_names = []
        if down_nodes_from_slurm_config := slurm_config.down_nodes:
            for down_nodes_entry in down_nodes_from_slurm_config:
                if down_nodes_entry.down_nodes:
                    for down_node_name in down_nodes_entry.down_nodes:
                        if down_nodes_entry.reason == "New node.":
                            new_node_names.append(down_node_name)
        return new_node_names

    def _check_status(self) -> bool:  # noqa C901
        """Check for all relations and set appropriate status.

        This charm needs these conditions to be satisfied in order to be ready:
        - Slurmctld component installed
        """
        if self.slurm_installed is not True:
            self.unit.status = BlockedStatus(
                "failed to install slurmctld. see logs for further details"
            )
            return False

        if self.cluster_name is None:
            self.unit.status = WaitingStatus("Waiting for cluster_name....")
            return False

        self.unit.status = ActiveStatus("")
        return True

    def get_auth_key(self) -> Optional[str]:
        """Get the stored auth key."""
        return str(self._stored.auth_key)

    def get_jwt_rsa(self) -> Optional[str]:
        """Get the stored jwt_rsa key."""
        return str(self._stored.jwt_rsa)

    def _resume_nodes(self, nodelist: List[str]) -> None:
        """Run scontrol to resume the specified node list."""
        scontrol("update", f"nodename={','.join(nodelist)}", "state=resume")

    @property
    def cluster_name(self) -> Optional[str]:
        """Return the cluster name."""
        return self._slurmctld_peer.cluster_name

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
        return self._slurmctld.hostname

    @property
    def _ingress_address(self) -> str:
        """Return the ingress_address from the peer relation if it exists."""
        if (peer_binding := self.model.get_binding(PEER_INTEGRATION_NAME)) is not None:
            ingress_address = f"{peer_binding.network.ingress_address}"
            logger.debug(f"Slurmctld ingress_address: {ingress_address}")
            return ingress_address
        raise IngressAddressUnavailableError("Ingress address unavailable")

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
