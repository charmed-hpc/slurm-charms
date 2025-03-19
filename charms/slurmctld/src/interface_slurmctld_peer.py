# Copyright (c) 2025 Omnivector, LLC
# See LICENSE file for licensing details.

"""SlurmctldPeer."""

import logging
from typing import Optional

from ops import Object

logger = logging.getLogger()


class SlurmctldPeerError(Exception):
    """Exception raised from slurmctld-peer interface errors."""

    @property
    def message(self) -> str:
        """Return message passed as argument to exception."""
        return self.args[0]


class SlurmctldPeer(Object):
    """SlurmctldPeer Interface."""

    def __init__(self, charm, relation_name):
        """Initialize the interface."""
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

    @property
    def _relation(self):
        """Slurmctld peer relation."""
        return self.framework.model.get_relation(self._relation_name)

    @property
    def cluster_name(self) -> Optional[str]:
        """Return the cluster_name from app relation data."""
        cluster_name = None
        if self._relation:
            if cluster_name_from_relation := self._relation.data[self.model.app].get(
                "cluster_name"
            ):
                cluster_name = cluster_name_from_relation
            logger.debug(f"## `slurmctld-peer` relation available. cluster_name: {cluster_name}.")
        else:
            logger.debug(
                "## `slurmctld-peer` relation not available yet, cannot get cluster_name."
            )
        return cluster_name

    @cluster_name.setter
    def cluster_name(self, name: str) -> None:
        """Set the cluster_name on app relation data."""
        if not self.framework.model.unit.is_leader():
            logger.debug("only leader can set the Slurm cluster name")
            return

        if not self._relation:
            raise SlurmctldPeerError(
                "`slurmctld-peer` relation not available yet, cannot set cluster_name."
            )

        self._relation.data[self.model.app]["cluster_name"] = name
