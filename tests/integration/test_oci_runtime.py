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

"""`oci-runtime` integration tests for the Slurm charms."""

import logging
from io import StringIO
from time import sleep

import jubilant
import pytest
from constants import APPTAINER_APP_NAME, SACKD_APP_NAME, SLURMCTLD_APP_NAME, SLURMD_APP_NAME
from dotenv import dotenv_values

logger = logging.getLogger(__name__)


def setup_apptainer(juju: jubilant.Juju) -> None:
    """Deploy and integrate `apptainer` with `slurmctld` and `slurmd`.

    Notes:
        - Sleep for five seconds after the `apptainer` app reaches active status
          to give the cluster enough time to reconfigure.
    """
    logger.info("deploy '%s'", APPTAINER_APP_NAME)
    juju.deploy(APPTAINER_APP_NAME, channel="latest/edge")

    logger.info(
        "integration '%s' application with '%s' application",
        APPTAINER_APP_NAME,
        SLURMCTLD_APP_NAME,
    )
    juju.integrate(APPTAINER_APP_NAME, SLURMCTLD_APP_NAME)
    logger.info(
        "integration '%s' application with '%s' application",
        APPTAINER_APP_NAME,
        SLURMD_APP_NAME,
    )
    juju.integrate(APPTAINER_APP_NAME, SLURMD_APP_NAME)

    juju.wait(lambda status: jubilant.all_active(status, APPTAINER_APP_NAME))
    sleep(5)


@pytest.mark.order(12)
def test_apptainer_oci_scheduling(juju: jubilant.Juju) -> None:
    """Test that Slurm can schedule jobs using Apptainer."""
    if APPTAINER_APP_NAME not in juju.status().apps:
        setup_apptainer(juju)

    sackd_unit = f"{SACKD_APP_NAME}/0"
    slurmd_unit = f"{SLURMD_APP_NAME}/0"

    logger.info("testing that '%s' is running jobs within OCI images", APPTAINER_APP_NAME)
    juju.exec("apptainer pull /tmp/jammy.sif docker://ubuntu:jammy", unit=slurmd_unit)
    result = juju.exec(
        f"srun -p {SLURMD_APP_NAME} --container=/tmp/jammy.sif cat /etc/os-release",
        unit=sackd_unit,
    ).stdout.strip()
    env = dotenv_values(stream=StringIO(result))

    assert env["VERSION_CODENAME"] == "jammy"
    assert env["VERSION_ID"] == "22.04"
