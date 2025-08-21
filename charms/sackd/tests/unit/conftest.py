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

"""Configure unit tests for the `sackd` charmed operator."""

import pytest
from charm import SackdCharm
from ops import testing
from pyfakefs.fake_filesystem import FakeFilesystem
from pytest_mock import MockerFixture


@pytest.fixture(scope="function")
def mock_ctx() -> testing.Context[SackdCharm]:
    """Mock `SackdCharm` context."""
    return testing.Context(SackdCharm)


@pytest.fixture(scope="function")
def mock_charm(mock_ctx, fs: FakeFilesystem, mocker: MockerFixture) -> testing.Context[SackdCharm]:
    """Mock `SackdCharm` context with fake filesystem.

    Warnings:
        - The mock charm context must come before the fake filesystem fixture,
          otherwise `ops.testing.Context` will fail to locate the `sackd` charm's
          charmcraft.yaml file.
    """
    fs.create_file("/etc/slurm/slurm.key", create_missing_dirs=True)
    fs.create_file("/etc/default/sackd", create_missing_dirs=True)
    mocker.patch("subprocess.run")

    return mock_ctx
