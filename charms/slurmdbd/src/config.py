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

"""Manage the configuration of the `slurmdbd` charmed operator."""

import logging
from typing import TYPE_CHECKING, Any, cast

import ops
from constants import (
    DEFAULT_SLURMDBD_CONFIG,
    OVERRIDES_CONFIG_FILE,
    PEER_INTEGRATION_NAME,
    STORAGE_CONFIG_FILE,
)
from hpc_libs.interfaces import DatabaseData
from hpc_libs.utils import StopCharm, get_ingress_address, plog
from slurm_ops import SlurmOpsError
from slurmutils import ModelError, SlurmdbdConfig
from state import slurmdbd_ready

if TYPE_CHECKING:
    from charm import SlurmdbdCharm

_logger = logging.getLogger(__name__)


def init_config(charm: "SlurmdbdCharm", /) -> None:
    """Initialize the `slurmdbd` service's configuration.

    This function "seeds" the starting point for the `slurmdbd` service's configuration;
    it provides the default configuration values used by the service, but it does not provide
    all the required configuration for `slurmdbd` to start successfully.
    """
    # Seed the `slurmdbd.conf` configuration file.
    config = SlurmdbdConfig(
        dbdhost=charm.slurmdbd.hostname,
        dbdaddr=get_ingress_address(charm, PEER_INTEGRATION_NAME),
        authalttypes=["auth/jwt"],
        authaltparameters={"jwt_key": f"{charm.slurmdbd.jwt.path}"},
        **DEFAULT_SLURMDBD_CONFIG,
    )
    charm.slurmdbd.config.dump(config)


def update_overrides(charm: "SlurmdbdCharm", /) -> None:
    """Update the `slurmdbd.conf.overrides` configuration file.

    Raises:
        StopCharm: Raised if the custom `slurmdbd.conf` configuration provided is invalid.
    """
    _logger.info("updating `%s`", OVERRIDES_CONFIG_FILE)
    try:
        config = SlurmdbdConfig.from_str(
            cast(str, charm.config.get("slurmdbd-conf-parameters", ""))
        )
    except (ModelError, ValueError) as e:
        _logger.error(e)
        raise StopCharm(
            ops.BlockedStatus(
                "Failed to load custom `slurmdbd` configuration. "
                + "See `juju debug-log` for details"
            )
        )

    _logger.debug("`%s`:\n%s", OVERRIDES_CONFIG_FILE, plog(config.dict()))
    charm.slurmdbd.config.includes[OVERRIDES_CONFIG_FILE].dump(config)
    _logger.info("`%s` successfully updated", OVERRIDES_CONFIG_FILE)


def update_storage(charm: "SlurmdbdCharm", /, config: dict[str, Any]) -> None:
    """Update the `slurmdbd.conf.storage` configuration file.

    Raises:
        StopCharm: Raised if the `slurmdbd.conf` database configuration provided is invalid.
    """
    _logger.info("updating `%s`", STORAGE_CONFIG_FILE)
    try:
        storage = SlurmdbdConfig.from_dict(config)
    except (ModelError, ValueError) as e:
        _logger.error(e)
        raise StopCharm(
            ops.BlockedStatus(
                "Failed to load database configuration for `slurmdbd`. "
                + "See `juju debug-log` for details"
            )
        )

    _logger.debug("`%s`:\n%s", STORAGE_CONFIG_FILE, plog(storage.dict()))
    charm.slurmdbd.config.includes[STORAGE_CONFIG_FILE].dump(storage)
    _logger.info("`%s` successfully updated", STORAGE_CONFIG_FILE)


def reconfigure_slurmdbd(charm: "SlurmdbdCharm") -> None:
    """Reconfigure and restart the `slurmdbd` service.

    Raises:
        SlurmOpsError: Raised if the `slurmdbd` service fails to start or restart.
    """
    if not slurmdbd_ready(charm):
        return

    try:
        charm.slurmdbd.config.merge()
        charm.slurmdbd.service.enable()
        charm.slurmdbd.service.restart()
    except SlurmOpsError as e:
        _logger.error(e.message)
        raise StopCharm(
            ops.BlockedStatus(
                "Failed to apply new `slurmdbd` configuration. See `juju debug-log` for details"
            )
        )

    charm.slurmctld.set_database_data(DatabaseData(hostname=charm.slurmdbd.hostname))
