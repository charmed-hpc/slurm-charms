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

"""Slurm charm integration tests."""

import logging

import jubilant
import pytest
import tenacity
from constants import (
    DEFAULT_SLURM_CHARM_CHANNEL,
    MYSQL_APP_NAME,
    SACKD_APP_NAME,
    SLURM_APPS,
    SLURMCTLD_APP_NAME,
    SLURMD_APP_NAME,
    SLURMDBD_APP_NAME,
    SLURMRESTD_APP_NAME,
)

logger = logging.getLogger(__name__)


@pytest.mark.order(1)
def test_deploy(juju: jubilant.Juju, base, sackd, slurmctld, slurmd, slurmdbd, slurmrestd) -> None:
    """Test if the Slurm charms can successfully reach active status."""
    # Deploy Slurm and auxiliary services.
    juju.deploy(
        sackd,
        SACKD_APP_NAME,
        base=base,
        channel=DEFAULT_SLURM_CHARM_CHANNEL if isinstance(sackd, str) else None,
    )
    # Controller uses a VM with low `SlurmctldTimeout` to facilitate HA tests
    juju.deploy(
        slurmctld,
        SLURMCTLD_APP_NAME,
        base=base,
        channel=DEFAULT_SLURM_CHARM_CHANNEL if isinstance(slurmctld, str) else None,
        constraints={"virt-type": "virtual-machine"},
        config={"slurm-conf-parameters": "SlurmctldTimeout=10\n"},
    )
    juju.deploy(
        slurmd,
        SLURMD_APP_NAME,
        base=base,
        channel=DEFAULT_SLURM_CHARM_CHANNEL if isinstance(slurmd, str) else None,
    )
    juju.deploy(
        slurmdbd,
        SLURMDBD_APP_NAME,
        base=base,
        channel=DEFAULT_SLURM_CHARM_CHANNEL if isinstance(slurmdbd, str) else None,
    )
    juju.deploy(
        slurmrestd,
        SLURMRESTD_APP_NAME,
        base=base,
        channel=DEFAULT_SLURM_CHARM_CHANNEL if isinstance(slurmrestd, str) else None,
    )
    juju.deploy("mysql", MYSQL_APP_NAME)

    # Integrate applications together.
    juju.integrate(SACKD_APP_NAME, SLURMCTLD_APP_NAME)
    juju.integrate(SLURMD_APP_NAME, SLURMCTLD_APP_NAME)
    juju.integrate(SLURMDBD_APP_NAME, SLURMCTLD_APP_NAME)
    juju.integrate(SLURMRESTD_APP_NAME, SLURMCTLD_APP_NAME)
    juju.integrate(MYSQL_APP_NAME, SLURMDBD_APP_NAME)

    # Wait for Slurm applications to reach active status.
    juju.wait(lambda status: jubilant.all_active(status, *SLURM_APPS))


@pytest.mark.order(2)
def test_slurm_services_are_active(juju: jubilant.Juju) -> None:
    """Test that all the Slurm services are active after deployment."""
    status = juju.status()
    for app, service in SLURM_APPS.items():
        for unit in status.apps[app].units:
            logger.info("testing that the '%s' service is active within unit '%s'", service, unit)
            result = juju.exec(f"systemctl is-active {service}", unit=unit)
            assert result.stdout.strip() == "active"


@pytest.mark.order(3)
def test_slurm_prometheus_exporter_service_is_active(juju: jubilant.Juju) -> None:
    """Test that the `prometheus-slurm-exporter` service is active within `controller/0`."""
    unit = f"{SLURMCTLD_APP_NAME}/0"

    logger.info(
        "testing that the 'prometheus-slurm-exporter' service is active within unit '%s/0'",
        unit,
    )
    result = juju.exec("systemctl is-active prometheus-slurm-exporter", unit=unit)
    assert result.stdout.strip() == "active"


@pytest.mark.order(4)
def test_slurmctld_port_number(juju: jubilant.Juju) -> None:
    """Test that the `slurmctld` service is listening on port 6817."""
    unit = f"{SLURMCTLD_APP_NAME}/0"
    port = 6817

    logger.info(
        "testing that the 'slurmctld' service is listening on port '%s' on unit '%s'",
        port,
        unit,
    )
    result = juju.exec("lsof", "-t", "-n", f"-iTCP:{port}", "-sTCP:LISTEN", unit=unit)
    assert result.stdout.strip() != ""


@pytest.mark.order(5)
def test_slurmdbd_port_number(juju: jubilant.Juju) -> None:
    """Test that the `slurmdbd` service is listening on port 6819."""
    unit = f"{SLURMDBD_APP_NAME}/0"
    port = 6819

    logger.info(
        "testing that the 'slurmctld' service is listening on port '%s' on unit '%s'",
        port,
        unit,
    )
    result = juju.exec(f"lsof -t -n -iTCP:{port} -sTCP:LISTEN", unit=unit)
    assert result.stdout.strip() != ""


@pytest.mark.order(6)
def test_new_slurmd_unit_state_and_reason(juju: jubilant.Juju) -> None:
    """Test that new nodes join the cluster in a down state and with an appropriate reason."""
    unit = f"{SACKD_APP_NAME}/0"

    logger.info("testing that a new slurmd unit is down with the reason: 'New node.'")
    reason = juju.exec("sinfo -R | awk '{print $1, $2}' | sed 1d | tr -d '\n'", unit=unit)
    state = juju.exec("sinfo | awk '{print $5}' | sed 1d | tr -d '\n'", unit=unit)
    assert reason.stdout == "New node."
    assert state.stdout == "down"


@pytest.mark.order(7)
@tenacity.retry(
    wait=tenacity.wait.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(3),
    reraise=True,
)
def test_node_configured_action(juju: jubilant.Juju) -> None:
    """Test that the node-configured charm action makes slurmd unit 'idle'.

    Warnings:
        There is some latency between when `node-configured` is run and when
        `compute/0` becomes active within Slurm. `tenacity` is used here to account
        for that delay by retrying this test over an expanding period of time to
        give Slurm some additional time to reconfigure itself.
    """
    unit = f"{SLURMD_APP_NAME}/0"

    logger.info("testing that the `node-configured` charm action makes node status 'idle'")
    juju.run(unit, "node-configured")
    state = juju.exec("sinfo | awk '{print $5}' | sed 1d | tr -d '\n'", unit=unit)
    assert state.stdout == "idle"


@pytest.mark.order(8)
def test_health_check_program(juju: jubilant.Juju) -> None:
    """Test that running the `healthcheckprogram` doesn't put the node in a drain state."""
    unit = f"{SLURMD_APP_NAME}/0"

    logger.info("testing that running node health check program doesn't drain node")
    juju.exec("/usr/sbin/charmed-hpc-nhc-wrapper", unit=unit)
    state = juju.exec("sinfo | awk '{print $5}' | sed 1d | tr -d '\n'", unit=unit)
    assert state.stdout == "idle"


@pytest.mark.order(9)
def test_job_submission_works(juju: jubilant.Juju) -> None:
    """Test that a job can be successfully submitted to the Slurm cluster."""
    sackd_unit = f"{SACKD_APP_NAME}/0"
    slurmd_unit = f"{SLURMD_APP_NAME}/0"

    logger.info("testing that a simple job can be submitted to slurm and successfully run")
    # Get the hostname of the compute node via `juju exec`.
    slurmd_result = juju.exec("hostname -s", unit=slurmd_unit)
    # Get the hostname of the compute node from a Slurm job.
    sackd_result = juju.exec(f"srun --partition {SLURMD_APP_NAME} hostname -s", unit=sackd_unit)
    assert sackd_result.stdout == slurmd_result.stdout
