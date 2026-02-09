#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
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

"""Unit tests for the `slurmd` charmed operators `config` module."""

import pytest
from config import ConfigManager
from ops import ConfigData
from slurm_ops import SlurmOpsError
from slurmutils import Partition

APP_NAME = "compute"


class TestConfigManager:
    """Unit tests for the `ConfigManager` class."""

    @pytest.mark.parametrize(
        "valid_config",
        (
            pytest.param(
                {
                    "default-node-state": "idle",
                    "default-node-reason": "",
                    "partition-config": "state=up maxtime=30-00:00:00",
                },
                id="idle no reason",
            ),
            pytest.param(
                {
                    "default-node-state": "down",
                    "default-node-reason": "maintenance",
                    "partition-config": "state=up maxtime=10-00:00:00",
                },
                id="down with reason",
            ),
            pytest.param(
                {
                    "default-node-state": "down",
                    "default-node-reason": "",
                    "partition-config": "state=down",
                },
                id="down empty reason",
            ),
        ),
    )
    def test_load_valid_config(self, valid_config: ConfigData) -> None:
        """Test the `load` method with valid configuration option values."""
        default_node_state = valid_config["default-node-state"]
        default_node_reason = valid_config["default-node-reason"]
        partition_config = Partition.from_str(valid_config["partition-config"])
        partition_config.partition_name = APP_NAME
        partition_config.nodes = [APP_NAME]

        config = ConfigManager.load(valid_config, APP_NAME)

        assert config.default_node_state == default_node_state

        if default_node_state != "idle" and not default_node_reason:
            assert config.default_node_reason == "n/a"
        else:
            assert config.default_node_reason == default_node_reason

        assert config.partition_config.dict() == partition_config.dict()

    @pytest.mark.parametrize(
        "invalid_config",
        (
            pytest.param(
                {
                    "default-node-state": "invalid",
                    "default-node-reason": "",
                    "partition-config": "state=up",
                },
                id="invalid state",
            ),
            pytest.param(
                {
                    "default-node-state": "idle",
                    "default-node-reason": "",
                    "partition-config": "invalidkey=value",
                },
                id="invalid partition",
            ),
        ),
    )
    def test_load_invalid_config(self, invalid_config: ConfigData) -> None:
        """Test the `load` method with invalid configuration option values."""
        with pytest.raises(SlurmOpsError) as exec_info:
            ConfigManager.load(invalid_config, APP_NAME)

        assert "failed validation" in exec_info.value.message
