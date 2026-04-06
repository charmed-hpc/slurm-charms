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

"""Configure `slurm-ops` unit tests."""

import subprocess
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture


@pytest.fixture(scope="function")
def mock_run(mocker: MockerFixture) -> Mock:
    """Request a mocked `subprocess.run(...)` function."""
    return mocker.patch.object(
        subprocess, "run", return_value=subprocess.CompletedProcess(args=[], returncode=0)
    )
