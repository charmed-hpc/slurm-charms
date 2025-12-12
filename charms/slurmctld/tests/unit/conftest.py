# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Configure unit tests for the `slurmctld` charmed operator."""

from unittest.mock import MagicMock

import pytest
from charm import SlurmctldCharm
from ops import testing
from pyfakefs.fake_filesystem import FakeFilesystem
from pytest_mock import MockerFixture


@pytest.fixture(scope="function")
def mock_scontrol(mocker: MockerFixture) -> MagicMock:
    """Mock the `scontrol` function from `slurm-ops`."""
    return mocker.patch("charm.scontrol")


@pytest.fixture(scope="function")
def mock_ctx() -> testing.Context[SlurmctldCharm]:
    """Mock `SlurmctldCharm` context."""
    return testing.Context(SlurmctldCharm)


@pytest.fixture(scope="function")
def mock_charm(
    mock_ctx, fs: FakeFilesystem, mocker: MockerFixture, mock_scontrol
) -> testing.Context[SlurmctldCharm]:
    """Mock `SlurmctldCharm` context with fake filesystem."""
    fs.create_file("/etc/slurm/slurm.key", create_missing_dirs=True)
    mocker.patch("shutil.chown")  # User/group `slurm` doesn't exist on host.
    mocker.patch("subprocess.run")
    return mock_ctx


@pytest.fixture(scope="function", params=(True, False), ids=("success", "failure"))
def succeed(request: pytest.FixtureRequest) -> bool:
    """Parameterize a test to succeed and fail."""
    return request.param
