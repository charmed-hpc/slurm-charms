# Copyright 2025-2026 Canonical Ltd.
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

"""Configure unit tests for the `slurmd` charmed operator."""

# Must come before SlurmdCharm import
from module_mocks import apt_pkg_mock, detect_mock  # noqa: F401 I001

import pytest
from charm import SlurmdCharm
from ops import testing
from pyfakefs.fake_filesystem import FakeFilesystem
from pytest_mock import MockerFixture


@pytest.fixture(scope="function")
def mock_ctx() -> testing.Context[SlurmdCharm]:
    """Mock `SlurmdCharm` context."""
    return testing.Context(SlurmdCharm)


@pytest.fixture(scope="function")
def mock_charm(
    mock_ctx, fs: FakeFilesystem, mocker: MockerFixture
) -> testing.Context[SlurmdCharm]:
    """Mock `SlurmdCharm` context with fake filesystem.

    Warnings:
        - The mock charm context must come before the fake filesystem fixture,
          otherwise `ops.testing.Context` will fail to locate the `slurmd` charm's
          charmcraft.yaml file.
    """
    fs.create_file("/etc/slurm/slurm.jwks", create_missing_dirs=True)
    fs.create_file("/etc/default/slurmd", create_missing_dirs=True)
    fs.create_dir("/usr/sbin")
    # TODO: Simplify charm lifecycle patches once Observer pattern is implemented.
    #   The `dcgm-exporter` manager must be patched to prevent a computer crashing
    #   memory leak that is triggered by the unit tests when creating the scenario
    #   `Context` object for the `SlurmdCharm` object. Deeper investigation shows that
    #   mocking `subprocess.run` does not play nicely with `pyfakefs`, and this seems to be where
    #   the memory leak is originating from. It is specifically triggered when `ops.main`
    #   is called by `Scenario` and the `SlurmdCharm` object's `__init__` method is called.
    #   The suspicion is that either `pyfakefs` or the `subprocess.run` mock is causing
    #   unbounded data duplication in memory when creating the fake filesystem.
    mocker.patch(
        "charmed_hpc_libs.ops.machine.nvidia.DCGMManager.exporter",
        new_callable=mocker.PropertyMock(),
    )
    mocker.patch("subprocess.run")

    return mock_ctx
