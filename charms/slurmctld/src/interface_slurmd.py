"""Slurmctld interface to slurmd."""

import json
import logging
from typing import Any, Dict

from ops import (
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
    Relation,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationCreatedEvent,
    RelationDepartedEvent,
    Unit,
)

logger = logging.getLogger()


class PartitionAvailableEvent(EventBase):
    """Emitted when slurmd application partition data is available on the relation."""


class PartitionUnavailableEvent(EventBase):
    """Emitted when a slurmd application integration is broken."""


class SlurmdAvailableEvent(EventBase):
    """Emitted when the slurmd unit joins the relation."""


class SlurmdDepartedEvent(EventBase):
    """Emitted when one slurmd departs."""


class Events(ObjectEvents):
    """Slurmd interface events."""

    partition_available = EventSource(PartitionAvailableEvent)
    partition_unavailable = EventSource(PartitionUnavailableEvent)
    slurmd_available = EventSource(SlurmdAvailableEvent)
    slurmd_departed = EventSource(SlurmdDepartedEvent)


class Slurmd(Object):
    """Slurmd inventory interface."""

    on = Events()  # pyright: ignore [reportIncompatibleMethodOverride, reportAssignmentType]

    def __init__(self, charm, relation_name):
        """Set self._relation_name and self.charm."""
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

        self.framework.observe(
            self._charm.on[self._relation_name].relation_created,
            self._on_relation_created,
        )
        self.framework.observe(
            self._charm.on[self._relation_name].relation_changed,
            self._on_relation_changed,
        )
        self.framework.observe(
            self._charm.on[self._relation_name].relation_departed,
            self._on_relation_departed,
        )
        self.framework.observe(
            self._charm.on[self._relation_name].relation_broken,
            self._on_relation_broken,
        )

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Set our data on the relation."""
        # Need to wait until the charm has installed slurm before we can proceed.
        if not self._charm.slurm_installed:
            event.defer()
            return

        health_check_params = (
            self._charm.config.get("health-check-params")
            if len(self._charm.config.get("health-check-params")) > 0
            else "#"
        )
        event.relation.data[self.model.app]["cluster_info"] = json.dumps(
            {
                "munge_key": self._charm.get_munge_key(),
                "slurmctld_host": self._charm.hostname,
                "cluster_name": self._charm.cluster_name,
                "nhc_params": health_check_params,
            }
        )

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Emit slurmd available event and conditionally update new_nodes."""
        if app := event.app:
            app_data = event.relation.data[app]
            if not app_data.get("partition"):
                logger.debug("No partition on relation.")
                event.defer()
                return
        else:
            logger.debug("No application on relation.")
            event.defer()
            return

        # The event.unit data isn't in the relation data on the first occurrence
        # of relation-changed so we check for it here in order to prevent things
        # from blowing up. Not much to do if we don't have it other than log
        # and proceed.
        if unit := event.unit:
            unit_data = event.relation.data[unit]
            if node_json := unit_data.get("node"):

                try:
                    node = json.loads(node_json)
                except json.JSONDecodeError as e:
                    logger.error(e)
                    raise e

                if node.get("new_node"):
                    if node_config := node.get("node_parameters"):
                        if node_name := node_config.get("NodeName"):
                            self._charm.new_nodes = list(set(self._charm.new_nodes + [node_name]))
                            self.on.slurmd_available.emit()
            else:
                logger.debug(f"`node` data does not exist for unit: {unit}.")
        else:
            logger.debug("Unit doesn't exist on the relation.")

        self.on.partition_available.emit()

    def _on_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Handle hook when 1 unit departs."""
        self.on.slurmd_departed.emit()

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Clear the munge key and emit the event if the relation is broken."""
        if self.framework.model.unit.is_leader():
            event.relation.data[self.model.app]["cluster_info"] = ""
            self.on.partition_unavailable.emit()

    def set_nhc_params(self, params: str) -> None:
        """Send NHC parameters to all slurmd."""
        # juju does not allow setting empty data/strings on the relation data,
        # so we set it to something that behaves like empty
        logger.debug(f"## set_nhc_params: {params}")

        if relations := self.framework.model.relations.get(self._relation_name):
            for relation in relations:
                app = self.model.app
                cluster_info = json.loads(relation.data[app]["cluster_info"])
                cluster_info["nhc_params"] = params
                relation.data[app]["cluster_info"] = json.dumps(cluster_info)
        else:
            logger.debug("## slurmd not joined")

    def _get_partition_from_relation(self, relation: Relation) -> Dict[str, Any]:
        """Get the partition from the relation."""
        partition_as_dict = {}
        if partition_as_json := relation.data[relation.app].get("partition"):
            # Decode the json partition relation data.
            try:
                partition_as_dict = json.loads(partition_as_json)
            except json.JSONDecodeError as e:
                logger.error(e)
                raise e
        return partition_as_dict

    def _get_node_from_relation(self, relation: Relation, unit: Unit) -> Dict[str, Any]:
        """Decode and return the node from the unit data on the relation."""
        node_as_dict = {}
        if node := relation.data[unit].get("node"):
            # Load the node
            try:
                node_as_dict = json.loads(node)
            except json.JSONDecodeError as e:
                logger.error(e)
                raise e

        return node_as_dict

    def get_new_nodes_and_nodes_and_partitions(self) -> Dict[str, Any]:
        """Return the new_nodes, nodes and partitions configuration.

        Iterate over the relation data to assemble the nodes, new_nodes
        and partition configuration.
        """
        partitions = {}
        nodes = {}
        new_nodes = []

        if relations := self.framework.model.relations.get(self._relation_name):
            for relation in relations:

                partition_as_dict = self._get_partition_from_relation(relation)
                # Account for the case where multiple slurmd applications relate at the same time.
                # This eliminates the possibility of iterating over relations for joined slurmd
                # applications who haven't yet set the 'partition' data on the relation.
                if not partition_as_dict:
                    continue

                # partition_as_dict should only contain a single top level partition name.
                # Iterate over partition_as_dict.items() as a convenience to get the partition_name
                # and partition_parameters without having to find the key name and then index.
                for partition_name, partition_parameters in partition_as_dict.items():

                    partition_nodes = []
                    for unit in relation.units:

                        if node := self._get_node_from_relation(relation, unit):

                            # Check that the data we expect to exist, exists.
                            if node_config := node.get("node_parameters"):

                                # Get the NodeName and append to the partition nodes
                                node_name = node_config["NodeName"]
                                partition_nodes.append(node_name)

                                # Add this node config to the nodes dict.
                                nodes[node_name] = {
                                    k: v for k, v in node_config.items() if k not in ["NodeName"]
                                }

                                # Account for new node.
                                if node.get("new_node"):
                                    new_nodes.append(node_name)

                    # Ensure we have a unique list and add it to the partition.
                    partition_parameters["Nodes"] = list(set(partition_nodes))

                    # Check for default partition.
                    if self._charm.model.config.get("default-partition") == partition_name:
                        partition_parameters["Default"] = "YES"

                    partitions[partition_name] = partition_parameters

        # If we have down nodes because they are new nodes, then set them here.
        new_node_down_nodes = (
            [{"DownNodes": list(set(new_nodes)), "State": "DOWN", "Reason": "New node."}]
            if len(new_nodes) > 0
            else []
        )
        return {"down_nodes": new_node_down_nodes, "nodes": nodes, "partitions": partitions}
