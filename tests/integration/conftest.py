#!/usr/bin/env python3
# Copyright 2023-2025 Canonical Ltd.
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

"""Configure Slurm charm integration tests."""

import logging
import os
from collections.abc import Iterator
from pathlib import Path

import jubilant
import pytest

logger = logging.getLogger(__name__)
LOCAL_SACKD = Path(sackd) if (sackd := os.getenv("LOCAL_SACKD")) else None
LOCAL_SLURMCTLD = Path(slurmctld) if (slurmctld := os.getenv("LOCAL_SLURMCTLD")) else None
LOCAL_SLURMD = Path(slurmd) if (slurmd := os.getenv("LOCAL_SLURMD")) else None
LOCAL_SLURMDBD = Path(slurmdbd) if (slurmdbd := os.getenv("LOCAL_SLURMDBD")) else None
LOCAL_SLURMRESTD = Path(slurmrestd) if (slurmrestd := os.getenv("LOCAL_SLURMRESTD")) else None


@pytest.fixture(scope="session")
def juju(request: pytest.FixtureRequest) -> Iterator[jubilant.Juju]:
    """Yield wrapper for interfacing with the `juju` CLI command."""
    keep_models = bool(request.config.getoption("--keep-models"))

    with jubilant.temp_model(keep=keep_models) as juju:
        juju.wait_timeout = 10 * 60

        yield juju

        if request.session.testsfailed:
            log = juju.debug_log(limit=1000)
            print(log, end="")


@pytest.fixture(scope="module")
def base(request: pytest.FixtureRequest) -> str:
    """Get the base to deploy the Slurm charms on."""
    return request.config.getoption("--charm-base")


@pytest.fixture(scope="module")
def sackd(request: pytest.FixtureRequest) -> Path | str:
    """Get `sackd` charm to use for the integration tests.

    If the `LOCAL_SACKD` environment variable is not set,
    the `sackd` charm will be pulled from the `latest/edge` channel
    on Charmhub instead.

    Returns:
        `Path` object if using a local `sackd` charm. `str` if pulling from Charmhub.
    """
    if not LOCAL_SACKD:
        logger.info("pulling `sackd` charm from the `latest/edge` channel on charmhub")
        return "sackd"

    logger.info("using local `sackd` charm located at %s", LOCAL_SACKD)
    return LOCAL_SACKD


@pytest.fixture(scope="module")
def slurmctld(request: pytest.FixtureRequest) -> Path | str:
    """Get `slurmctld` charm to use for the integration tests.

    If the `LOCAL_SLURMCTLD` environment variable is not set,
    the `sackd` charm will be pulled from the `latest/edge` channel
    on Charmhub instead.

    Returns:
        `Path` object if using a local `slurmctld` charm. `str` if pulling from Charmhub.
    """
    if not LOCAL_SLURMCTLD:
        logger.info("pulling `slurmctld` charm from the `latest/edge` channel on charmhub")
        return "slurmctld"

    logger.info("using local `slurmctld` charm located at %s", LOCAL_SLURMCTLD)
    return LOCAL_SLURMCTLD


@pytest.fixture(scope="module")
def slurmd(request: pytest.FixtureRequest) -> Path | str:
    """Get `slurmd` charm to use for the integration tests.

    If the `LOCAL_SLURMD` environment variable is not set,
    the `sackd` charm will be pulled from the `latest/edge` channel
    on Charmhub instead.

    Returns:
        `Path` object if using a local `slurmd` charm. `str` if pulling from Charmhub.
    """
    if not LOCAL_SLURMD:
        logger.info("pulling `slurmd` charm from the `latest/edge` channel on charmhub")
        return "slurmd"

    logger.info("using local `slurmd` charm located at %s", LOCAL_SLURMD)
    return LOCAL_SLURMD


@pytest.fixture(scope="module")
def slurmdbd(request: pytest.FixtureRequest) -> Path | str:
    """Get `slurmdbd` charm to use for the integration tests.

    If the `LOCAL_SLURMDBD` environment variable is not set,
    the `sackd` charm will be pulled from the `latest/edge` channel
    on Charmhub instead.

    Returns:
        `Path` object if using a local `slurmdbd` charm. `str` if pulling from Charmhub.
    """
    if not LOCAL_SLURMDBD:
        logger.info("pulling `slurmdbd` charm from the `latest/edge` channel on charmhub")
        return "slurmdbd"

    logger.info("using local `slurmdbd` charm located at %s", LOCAL_SLURMDBD)
    return LOCAL_SLURMDBD


@pytest.fixture(scope="module")
def slurmrestd(request: pytest.FixtureRequest) -> Path | str:
    """Get `slurmrestd` charm to use for the integration tests.

    If the `LOCAL_SLURMRESTD` environment variable is not set,
    the `sackd` charm will be pulled from the `latest/edge` channel
    on Charmhub instead.

    Returns:
        `Path` object if using a local `slurmrestd` charm. `str` if pulling from Charmhub.
    """
    if not LOCAL_SLURMRESTD:
        logger.info("pulling `slurmrestd` charm from the `latest/edge` channel on charmhub")
        return "slurmrestd"

    logger.info("using local `slurmrestd` charm located at %s", LOCAL_SLURMRESTD)
    return LOCAL_SLURMRESTD


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--charm-base",
        action="store",
        default="ubuntu@24.04",
        help="the base to deploy the slurm charms on during the integration tests",
    )
    parser.addoption(
        "--keep-models",
        action="store_true",
        default=False,
        help="keep temporarily created models",
    )
    parser.addoption(
        "--run-high-availability",
        action="store_true",
        default=False,
        help="run high availability tests (slow)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "high_availability: marks tests for slurmctld high availability"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-high-availability"):
        # Flag given in cli: do not skip tests
        return
    skip_ha = pytest.mark.skip(reason="need --run-high-availability option to run")
    for item in items:
        if "high_availability" in item.keywords:
            item.add_marker(skip_ha)
