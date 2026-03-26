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

from pydantic import BaseModel, ConfigDict, field_validator
from slurmutils import CGroupConfig, ModelError, SlurmConfig

_logger = logging.getLogger(__name__)


class ConfigManager(BaseModel):
    """Interface to the `slurmctld` application configuration."""

    # FIXME: `arbitrary_types_allowed=True` must be used here since pydantic cannot construct
    #  a schema for the `SlurmConfig` and `CGroupConfig` objects. This config can be removed when
    #  slurmutils v2 has transitioned to using pydantic models rather than custom ones.
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    cgroup_parameters: CGroupConfig
    cluster_name: str
    default_partition: str
    email_from_name: str
    slurm_conf_parameters: SlurmConfig

    @field_validator("slurm_conf_parameters", mode="before")
    @classmethod
    def _build_slurm_conf_parameters(cls, value: str) -> SlurmConfig:
        try:
            config = SlurmConfig.from_str(value)
        except (ModelError, ValueError) as e:
            raise ValueError(f"Invalid slurm configuration override: {value}. Reason:\n{e}")

        # Ensure `configless` mode is still enabled within the custom configuration.
        # The cluster will be corrupted if configless mode is unintentionally disabled.
        if config.slurmctld_parameters:
            config.slurmctld_parameters["enable_configless"] = True

        return config

    @field_validator("cgroup_parameters", mode="before")
    @classmethod
    def _build_cgroup_parameters(cls, value: str) -> CGroupConfig:
        config = CGroupConfig()
        config.constrain_cores = True
        config.constrain_devices = True
        config.constrain_ram_space = True
        config.constrain_swap_space = True
        config.signal_children_processes = True

        try:
            config.update(CGroupConfig.from_str(value))
        except (ModelError, ValueError) as e:
            raise ValueError(f"Invalid cgroup configuration: {value}. Reason:\n{e}")

        return config
