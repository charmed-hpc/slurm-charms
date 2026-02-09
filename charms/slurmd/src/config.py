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

"""Manage the configuration of the `slurmd` charmed operator."""

import logging
from typing import Literal

from ops import ConfigData
from pydantic import BaseModel, ConfigDict, ValidationError, ValidationInfo, field_validator
from slurm_ops import SlurmOpsError
from slurmutils import ModelError, Partition

_logger = logging.getLogger(__name__)


class ConfigManager(BaseModel):
    """Interface to `slurmd` application configuration options."""

    # FIXME: `arbitrary_types_allowed=True` must be used here since pydantic cannot construct
    #  a schema for the `Partition` object. This config can be removed when slurmutils v2 has
    #  transitioned to using pydantic models rather than custom ones.
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    # `app_name` must be public because private attributes are not accessible by validators.
    #   See: https://github.com/pydantic/pydantic/issues/7142
    app_name: str
    default_node_state: Literal["idle", "down"]
    default_node_reason: str
    partition_config: Partition

    @classmethod
    def load(cls, config: ConfigData, /, app_name: str) -> "ConfigManager":
        """Load `slurmd` application configuration options.

        Args:
            config: `slurmd` charmed application configuration data.
            app_name: Name of the `slurmd` application.

        Raises:
            SlurmOpsError: Raised if a configuration option fails validation.
        """
        try:
            return cls(
                app_name=app_name,
                default_node_state=config.get("default-node-state"),  # type: ignore
                default_node_reason=config.get("default-node-reason"),  # type: ignore
                partition_config=config.get("partition-config"),  # type: ignore
            )
        except ValidationError as e:
            _logger.error(e)
            raise SlurmOpsError(
                "Configuration option(s) "
                + ", ".join(
                    [
                        f"'{option.replace('_', '-')}'"  # type: ignore
                        for error in e.errors()
                        for option in error.get("loc", ())
                    ]
                )
                + " failed validation. See `juju debug-log` for details"
            )

    @field_validator("default_node_reason", mode="after")
    @classmethod
    def _empty_node_reason(cls, value: str, info: ValidationInfo) -> str:
        if (
            # Do not mutate `default_node_reason` if `default_node_state` failed validation.
            "default_node_state" in info.data
            and info.data["default_node_state"] != "idle"
            and not value
        ):
            return "n/a"

        return value

    @field_validator("partition_config", mode="before")
    @classmethod
    def _build_partition(cls, value: str, info: ValidationInfo) -> Partition:
        try:
            partition = Partition.from_str(value)
        except (ModelError, ValueError) as e:
            raise ValueError(f"Invalid partition configuration: {value}. Reason:\n{e}")

        name = info.data["app_name"]
        partition.partition_name = name
        partition.nodes = [name]
        return partition
