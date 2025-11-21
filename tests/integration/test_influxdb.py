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

"""`influxdb` integration tests for the Slurm charms."""

import logging
from time import sleep

import jubilant
import pytest
from constants import INFLUXDB_APP_NAME, SACKD_APP_NAME, SLURMCTLD_APP_NAME

logger = logging.getLogger(__name__)


def setup_influxdb(juju: jubilant.Juju) -> None:
    """Deploy and integrate `influxdb` with `slurmctld`.

    Notes:
        - Sleep for five seconds after the `influxdb` app reaches active status
          to give the cluster enough time to reconfigure.
    """
    logger.info("deploying '%s'", INFLUXDB_APP_NAME)
    juju.deploy(INFLUXDB_APP_NAME)

    logger.info("integrating '%s' application with '%s' application")
    juju.integrate(INFLUXDB_APP_NAME, SLURMCTLD_APP_NAME)

    juju.wait(lambda status: jubilant.all_active(status, INFLUXDB_APP_NAME))
    sleep(5)


@pytest.mark.order(11)
def test_task_accounting_works(juju: jubilant.Juju) -> None:
    """Test that `influxdb` is recording task level info."""
    if INFLUXDB_APP_NAME not in juju.status().apps:
        setup_influxdb(juju)

    unit = f"{SACKD_APP_NAME}/0"

    logger.info("testing that '%s' is recording task level info", INFLUXDB_APP_NAME)
    juju.scp(
        "tests/integration/testdata/sbatch_sleep_job.sh",
        f"ubuntu@{unit}:~/sbatch_sleep_job.sh",
    )
    job_id = juju.exec(
        "sbatch", "--parsable", "/home/ubuntu/sbatch_sleep_job.sh", unit=unit
    ).stdout.strip()

    logger.info("\n" + juju.exec("squeue", unit=unit).stdout)

    # Give a few seconds for the job to enter the queue and transition to RUNNING (takes ~ 5s).
    sleep(5)

    logger.info("\n" + juju.exec("squeue", unit=unit).stdout)

    result = juju.exec("sstat", job_id, "--format=NTasks", "--noheader", unit=unit).stdout.strip()
    logger.info("\n" + result)
    assert int(result) == 1
