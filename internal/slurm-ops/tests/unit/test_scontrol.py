#!/usr/bin/env python3
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

"""Unit tests for the `scontrol` utility function."""

from subprocess import CalledProcessError

import pytest
from slurm_ops import SlurmOpsError, scontrol


def test_scontrol_reconfigure(mock_run) -> None:
    """Test that the command `scontrol reconfigure` is called successfully."""
    scontrol("reconfigure")
    assert mock_run.call_args[0][0] == ["scontrol", "reconfigure"]


def test_scontrol_update(mock_run) -> None:
    """Test that the command `scontrol update ...` is called successfully."""
    scontrol("update", "nodename=test", "state=down", "reason='maintenance'")
    assert mock_run.call_args[0][0] == [
        "scontrol",
        "update",
        "nodename=test",
        "state=down",
        "reason='maintenance'",
    ]


def test_scontrol_error(mock_run) -> None:
    """Test that `scontrol` raises a `SlurmOpsError` if there is a failure."""
    mock_run.side_effect = CalledProcessError(
        cmd="scontrol ping", returncode=1, stderr="timeout connecting to controller"
    )

    with pytest.raises(SlurmOpsError) as exec_info:
        scontrol("ping")

    assert exec_info.type == SlurmOpsError
    assert exec_info.value.message == (
        "scontrol command 'scontrol ping' failed with exit code 1. "
        + "reason: timeout connecting to controller"
    )
