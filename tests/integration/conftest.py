#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
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

"""Configure slurmctld operator integration tests."""

import logging
import os
from pathlib import Path
from typing import Union

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)
SLURMCTLD_DIR = Path(slurmctld) if (slurmctld := os.getenv("SLURMCTLD_DIR")) else None
SLURMD_DIR = Path(slurmd) if (slurmd := os.getenv("SLURMD_DIR")) else None
SLURMDBD_DIR = Path(slurmdbd) if (slurmdbd := os.getenv("SLURMDBD_DIR")) else None
SLURMRESTD_DIR = Path(slurmrestd) if (slurmrestd := os.getenv("SLURMRESTD_DIR")) else None
SACKD_DIR = Path(sackd) if (sackd := os.getenv("SACKD_DIR")) else None


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--charm-base",
        action="store",
        default="ubuntu@24.04",
        help="Charm base version to use for integration tests",
    )


@pytest.fixture(scope="module")
def charm_base(request) -> str:
    """Get slurmctld charm base to use."""
    return request.config.option.charm_base


@pytest.fixture(scope="module")
async def slurmctld_charm(request, ops_test: OpsTest) -> Union[str, Path]:
    """Pack slurmctld charm to use for integration tests.

    If the `SLURMCTLD_DIR` environment variable is not set, this will pull the charm from
    Charmhub instead.

    Returns:
        `Path` if "slurmctld" is built locally. `str` otherwise.
    """
    if not SLURMCTLD_DIR:
        logger.info("Pulling slurmctld from Charmhub")
        return "slurmctld"

    return await ops_test.build_charm(SLURMCTLD_DIR, verbosity="verbose")


@pytest.fixture(scope="module")
async def slurmd_charm(request, ops_test: OpsTest) -> Union[str, Path]:
    """Pack slurmd charm to use for integration tests.

    If the `SLURMD_DIR` environment variable is not set, this will pull the charm from
    Charmhub instead.

    Returns:
        `Path` if "slurmd" is built locally. `str` otherwise.
    """
    if not SLURMD_DIR:
        logger.info("Pulling slurmd from Charmhub")
        return "slurmd"

    return await ops_test.build_charm(SLURMD_DIR, verbosity="verbose")


@pytest.fixture(scope="module")
async def slurmdbd_charm(request, ops_test: OpsTest) -> Union[str, Path]:
    """Pack slurmdbd charm to use for integration tests.

    If the `SLURMDBD_DIR` environment variable is not set, this will pull the charm from
    Charmhub instead.

    Returns:
        `Path` if "slurmdbd" is built locally. `str` otherwise..
    """
    if not SLURMDBD_DIR:
        logger.info("Pulling slurmdbd from Charmhub")
        return "slurmdbd"

    return await ops_test.build_charm(SLURMDBD_DIR, verbosity="verbose")


@pytest.fixture(scope="module")
async def slurmrestd_charm(request, ops_test: OpsTest) -> Union[str, Path]:
    """Pack slurmrestd charm to use for integration tests.

    If the `SLURMRESTD_DIR` environment variable is not set, this will pull the charm from
    Charmhub instead.

    Returns:
        `Path` if "slurmrestd" is built locally. `str` otherwise..
    """
    if not SLURMRESTD_DIR:
        logger.info("Pulling slurmrestd from Charmhub")
        return "slurmrestd"

    return await ops_test.build_charm(SLURMRESTD_DIR, verbosity="verbose")


@pytest.fixture(scope="module")
async def sackd_charm(request, ops_test: OpsTest) -> Union[str, Path]:
    """Pack sackd_charm charm to use for integration tests.

    If the `SACKD_DIR` environment variable is not set, this will pull the charm from
    Charmhub instead.

    Returns:
        `Path` if "sackd" is built locally. `str` otherwise..
    """
    if not SACKD_DIR:
        logger.info("Pulling sackd from Charmhub")
        return "sackd"

    return await ops_test.build_charm(SACKD_DIR, verbosity="verbose")
