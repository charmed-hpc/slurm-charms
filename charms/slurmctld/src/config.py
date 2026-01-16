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

"""Manage the configuration of the `slurmctld` charmed operator."""

import logging
from typing import TYPE_CHECKING, cast

import ops
from constants import (
    DEFAULT_CGROUP_CONFIG,
    DEFAULT_GRES_CONFIG,
    DEFAULT_SLURM_CONFIG,
    OVERRIDES_CONFIG_FILE,
)
from hpc_libs.interfaces import ControllerData
from hpc_libs.is_container import is_container
from hpc_libs.utils import StopCharm, plog
from slurm_ops import SlurmOpsError, scontrol
from slurmutils import CGroupConfig, GresConfig, ModelError, SlurmConfig
from state import slurmctld_ready

if TYPE_CHECKING:
    from charm import SlurmctldCharm

_logger = logging.getLogger(__name__)


def init_config(charm: "SlurmctldCharm") -> None:
    """Initialize the `slurmctld` service's configuration.

    This function "seeds" the starting point for the `slurmctld` service's configuration;
    it provides the configuration values required for the `slurmctld` service to start
    successfully and ready to start enlisting `slurmd` nodes.
    """
    # Seed the `slurm.conf` configuration file.
    data = charm.slurmctld_peer.get_controller_peer_app_data()
    config = SlurmConfig(
        clustername=data.cluster_name if data else "",
        slurmctldhost=get_controllers(charm),
        **DEFAULT_SLURM_CONFIG,
    )
    charm.slurmctld.config.dump(config)

    # Seed default `slurm.conf.<include>` configuration files.
    #
    # This "odd" context manager invocation enables us to ensure that the `slurm.conf.<include>`
    # file is created, but not overwrite any pre-existing content if `_on_start` is called
    # after the initial charm deployment sequence.
    for config in DEFAULT_SLURM_CONFIG["include"]:
        with charm.slurmctld.config.includes[config].edit() as _:
            pass

    # Create default gres.conf
    gres_config = GresConfig(**DEFAULT_GRES_CONFIG)
    charm.slurmctld.gres.dump(gres_config)


def get_controllers(charm: "SlurmctldCharm") -> list[str]:
    """Get hostnames for all controllers."""
    # Read the current list of controllers from the slurm.conf file and compare with the
    # controllers currently in the peer relation.
    # File ordering must be preserved as it dictates which slurmctld instance is the primary and
    # which are backups.
    from_file = charm.slurmctld.get_controllers()
    from_peer = charm.slurmctld_peer.get_controllers()

    _logger.debug(
        "controllers from slurm.conf: %s, from peer integration: %s", from_file, from_peer
    )

    # Controllers in the file but not the peer relation have departed.
    # Controllers in the peer relation but not the file are newly added.
    from_file_set = set(from_file)
    current_controllers = [c for c in from_file if c in from_peer] + [
        c for c in from_peer if c not in from_file_set
    ]

    _logger.debug("current controllers: %s", current_controllers)
    return current_controllers


def update_cgroup_config(charm: "SlurmctldCharm") -> None:
    """Update the `cgroup.conf` configuration file.

    Raises:
        StopCharm: Raised if the custom `cgroup.conf` configuration provided is invalid.
    """
    if is_container():
        data = charm.slurmctld_peer.get_controller_peer_app_data()
        _logger.warning(
            "'%s' machine is a container. not enabling cgroup support for '%s'",
            charm.unit.name,
            data.cluster_name if data else "",
        )
        return

    _logger.info("updating `cgroup.conf`")
    config = CGroupConfig(DEFAULT_CGROUP_CONFIG)
    try:
        config.update(CGroupConfig.from_str(cast(str, charm.config.get("cgroup-parameters", ""))))
    except (ModelError, ValueError) as e:
        _logger.error(e)
        raise StopCharm(
            ops.BlockedStatus(
                "Failed to load custom Slurm cgroup configuration. "
                + "See `juju debug-log` for details"
            )
        )

    _logger.debug("`cgroup.conf`:\n%s", plog(config.dict()))
    charm.slurmctld.cgroup.dump(config)
    _logger.info("`cgroup.conf` successfully updated")


def update_default_partition(charm: "SlurmctldCharm") -> None:
    """Update the configured default partition in `slurm.conf.<partition>`."""
    new_default = charm.config.get("default-partition", "")
    current_default = charm.slurmctld.get_default_partition()

    if new_default != current_default:
        includes = charm.slurmctld.config.includes
        new_default_include = includes[f"slurm.conf.{new_default}"]
        current_default_include = includes[f"slurm.conf.{current_default}"]

        if new_default != "" and new_default_include.exists():
            with new_default_include.edit() as config:
                config.partitions[new_default].default = True

        if current_default != "" and current_default_include.exists():
            with current_default_include.edit() as config:
                config.partitions[current_default].default = False


def update_overrides(charm: "SlurmctldCharm") -> None:
    """Update the `slurm.conf.overrides` configuration file.

    Raises:
        StopCharm: Raised if the custom `slurm.conf` configuration provided is invalid.
    """
    _logger.info("updating `%s`", OVERRIDES_CONFIG_FILE)
    try:
        config = SlurmConfig.from_str(cast(str, charm.config.get("slurm-conf-parameters", "")))
    except (ModelError, ValueError) as e:
        _logger.error(e)
        raise StopCharm(
            ops.BlockedStatus(
                "Failed to load custom Slurm configuration. See `juju debug-log` for details"
            )
        )

    # Ensure `configless` mode is still enabled within the custom configuration.
    # The cluster will be corrupted if configless mode is unintentionally disabled.
    if config.slurmctld_parameters:
        config.slurmctld_parameters["enable_configless"] = True

    _logger.debug("`%s`:\n%s", OVERRIDES_CONFIG_FILE, plog(config.dict()))
    charm.slurmctld.config.includes[OVERRIDES_CONFIG_FILE].dump(config)
    _logger.info("`%s` successfully updated", OVERRIDES_CONFIG_FILE)


def reconfigure_slurmctld(charm: "SlurmctldCharm") -> None:
    """Reconfigure the `slurmctld` service.

    In a `slurmctld` high availability setup, all `slurmctld` services across all `slurmctld` units
    in the cluster are restarted by this function. This ensures all `slurm.conf` changes are picked
    up, including those not re-read by an `scontrol reconfigure` command. If a restart is not done,
    removal of a controller will result in a malfunctioning cluster as `SlurmctldHost` lines are not
    re-read and an availability event may cause a failover attempt to a nonexistent backup.

    Raises:
        SlurmOpsError: Raised if the `scontrol reconfigure` command fails.
    """
    if not slurmctld_ready(charm):
        return

    # This must occur before `scontrol reconfigure` in case the primary `slurmctld` has been
    # removed and this unit is a backup being promoted to the new primary.
    #
    # If the `scontrol reconfigure` is performed first in this situation, it fails with:
    #   '['scontrol', 'reconfigure']' failed with exit code 1. reason: slurm_reconfigure error:
    #   Slurm backup controller in standby mode
    try:
        charm.slurmctld.service.restart()
    except SlurmOpsError as e:
        _logger.error(e.message)
        raise StopCharm(
            ops.BlockedStatus(
                "Failed to restart `slurmctld.service`. See `juju debug-log` for details"
            )
        )
    charm.slurmctld_peer.signal_slurmctld_restart()

    try:
        scontrol("reconfigure")
    except SlurmOpsError as e:
        _logger.error(e.message)
        raise StopCharm(
            ops.BlockedStatus(
                "Failed to apply new Slurm configuration. See `juju debug-log` for details"
            )
        )

    if charm.slurmrestd.is_joined():
        charm.slurmrestd.set_controller_data(
            ControllerData(
                slurmconfig={
                    "slurm.conf": charm.slurmctld.config.load(),
                    **{k: v.load() for k, v in charm.slurmctld.config.includes.items()},
                }
            )
        )
