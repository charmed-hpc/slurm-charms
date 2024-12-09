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

"""Test slurmctld charm against other SLURM operators."""

import asyncio
import logging

import pytest
import tenacity
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

SLURMCTLD = "slurmctld"
SLURMD = "slurmd"
SLURMDBD = "slurmdbd"
SLURMRESTD = "slurmrestd"
SACKD = "sackd"
DATABASE = "mysql"
ROUTER = "mysql-router"
SLURM_APPS = [SLURMCTLD, SLURMD, SLURMDBD, SLURMRESTD, SACKD]


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
@pytest.mark.order(1)
async def test_build_and_deploy_against_edge(
    ops_test: OpsTest,
    charm_base: str,
    slurmctld_charm,
    slurmd_charm,
    slurmdbd_charm,
    slurmrestd_charm,
    sackd_charm,
) -> None:
    """Test that the slurmctld charm can stabilize against slurmd, slurmdbd, slurmrestd, sackd, and MySQL."""
    logger.info(f"Deploying {', '.join(SLURM_APPS)}, and {DATABASE}")
    # Pack charms and download NHC resource for the slurmd operator.
    slurmctld, slurmd, slurmdbd, slurmrestd, sackd = await asyncio.gather(
        slurmctld_charm, slurmd_charm, slurmdbd_charm, slurmrestd_charm, sackd_charm
    )
    # Deploy the test Charmed SLURM cloud.
    await asyncio.gather(
        ops_test.model.deploy(
            str(slurmctld),
            application_name=SLURMCTLD,
            num_units=1,
            base=charm_base,
        ),
        ops_test.model.deploy(
            str(slurmd),
            application_name=SLURMD,
            channel="edge" if isinstance(slurmd, str) else None,
            num_units=1,
            base=charm_base,
        ),
        ops_test.model.deploy(
            str(slurmdbd),
            application_name=SLURMDBD,
            channel="edge" if isinstance(slurmdbd, str) else None,
            num_units=1,
            base=charm_base,
        ),
        ops_test.model.deploy(
            str(slurmrestd),
            application_name=SLURMRESTD,
            channel="edge" if isinstance(slurmrestd, str) else None,
            num_units=1,
            base=charm_base,
        ),
        ops_test.model.deploy(
            str(sackd),
            application_name=SACKD,
            channel="edge" if isinstance(sackd, str) else None,
            num_units=1,
            base=charm_base,
        ),
        # TODO:
        #   Re-enable `mysql-router` in the integration tests once `dpe/edge`
        #   channel supports the `ubuntu@24.04` base.
        # ops_test.model.deploy(
        #     ROUTER,
        #     application_name=f"{SLURMDBD}-{ROUTER}",
        #     channel="dpe/edge",
        #     num_units=0,
        #     base=charm_base,
        # ),
        ops_test.model.deploy(
            DATABASE,
            application_name=DATABASE,
            channel="8.0/edge",
            num_units=1,
            base="ubuntu@22.04",
        ),
    )
    # Set integrations for charmed applications.
    await ops_test.model.integrate(f"{SLURMCTLD}:{SLURMD}", f"{SLURMD}:{SLURMCTLD}")
    await ops_test.model.integrate(f"{SLURMCTLD}:{SLURMDBD}", f"{SLURMDBD}:{SLURMCTLD}")
    await ops_test.model.integrate(f"{SLURMCTLD}:{SLURMRESTD}", f"{SLURMRESTD}:{SLURMCTLD}")
    await ops_test.model.integrate(f"{SLURMCTLD}:login-node", f"{SACKD}:{SLURMCTLD}")
    # await ops_test.model.integrate(f"{SLURMDBD}-{ROUTER}:backend-database", f"{DATABASE}:database")
    await ops_test.model.integrate(f"{SLURMDBD}:database", f"{DATABASE}:database")
    # Reduce the update status frequency to accelerate the triggering of deferred events.
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=SLURM_APPS, status="active", timeout=1000)
        for app in SLURM_APPS:
            assert ops_test.model.applications[app].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
@pytest.mark.order(2)
@tenacity.retry(
    wait=tenacity.wait.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(3),
    reraise=True,
)
async def test_munge_is_active(ops_test: OpsTest) -> None:
    """Test that munge is active inside all the SLURM units."""
    for app in SLURM_APPS:
        logger.info(f"Checking that munge is active inside {app}.")
        unit = ops_test.model.applications[app].units[0]
        res = (await unit.ssh("systemctl is-active munge")).strip("\n")
        assert res == "active"


@pytest.mark.abort_on_fail
@pytest.mark.order(3)
@tenacity.retry(
    wait=tenacity.wait.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(3),
    reraise=True,
)
async def test_services_are_active(ops_test: OpsTest) -> None:
    """Test that the SLURM services are active inside the SLURM units."""
    for app in SLURM_APPS:
        logger.info(f"Checking that the {app} service is active inside the {app} unit.")
        unit = ops_test.model.applications[app].units[0]
        res = (await unit.ssh(f"systemctl is-active {app}")).strip("\n")
        assert res == "active"


@pytest.mark.abort_on_fail
@pytest.mark.order(4)
@tenacity.retry(
    wait=tenacity.wait.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(3),
    reraise=True,
)
async def test_slurmctld_port_listen(ops_test: OpsTest) -> None:
    """Test that slurmctld is listening on port 6817."""
    logger.info("Checking that slurmctld is listening on port 6817")
    slurmctld_unit = ops_test.model.applications[SLURMCTLD].units[0]
    res = await slurmctld_unit.ssh("sudo lsof -t -n -iTCP:6817 -sTCP:LISTEN")
    assert res != ""


@pytest.mark.abort_on_fail
@pytest.mark.order(5)
@tenacity.retry(
    wait=tenacity.wait.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(3),
    reraise=True,
)
async def test_slurmdbd_port_listen(ops_test: OpsTest) -> None:
    """Test that slurmdbd is listening on port 6819."""
    logger.info("Checking that slurmdbd is listening on port 6819")
    slurmdbd_unit = ops_test.model.applications[SLURMDBD].units[0]
    res = await slurmdbd_unit.ssh("sudo lsof -t -n -iTCP:6819 -sTCP:LISTEN")
    assert res != ""
