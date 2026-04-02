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

from pydantic import BaseModel, ConfigDict, field_validator
from slurmutils import ModelError, SlurmdbdConfig

_logger = logging.getLogger(__name__)


class ConfigManager(BaseModel):
    """Interface to `slurmdbd` application configuration options."""

    # FIXME: `arbitrary_types_allowed=True` must be used here since pydantic cannot construct
    #  a schema for the `SlurmdbdConfig` object. This config can be removed when slurmutils v2 has
    #  transitioned to using pydantic models rather than custom ones.
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    slurmdbd_conf_parameters: SlurmdbdConfig

    @field_validator("slurmdbd_conf_parameters", mode="before")
    @classmethod
    def _build_slurmdbd_conf_parameters(cls, value: str) -> SlurmdbdConfig:
        try:
            config = SlurmdbdConfig.from_str(value)
        except (ModelError, ValueError) as e:
            raise ValueError(f"Invalid slurmdbd configuration override: {value}. Reason:\n{e}")

        return config
