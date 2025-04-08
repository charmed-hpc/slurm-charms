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
import pathlib
from collections.abc import Awaitable

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
INFLUXDB = "influxdb"
ROUTER = "mysql-router"
SLURM_APPS = [SLURMCTLD, SLURMD, SLURMDBD, SLURMRESTD, SACKD]


async def build_and_deploy_charm(
    ops_test: OpsTest, charm: Awaitable[str | pathlib.Path], *deploy_args, **deploy_kwargs
):
    """Build and deploy the charm identified by `charm`."""
    charm = await charm
    deploy_kwargs["channel"] = "edge" if isinstance(charm, str) else None
    await ops_test.model.deploy(str(charm), *deploy_args, **deploy_kwargs)


@pytest.mark.abort_on_fail
@pytest.mark.skip_if_deployed
@pytest.mark.order(1)
async def test_build_and_deploy_against_edge(
    ops_test: OpsTest,
    charm_base: str,
    slurmctld_charm: Awaitable[str | pathlib.Path],
    slurmd_charm: Awaitable[str | pathlib.Path],
    slurmdbd_charm: Awaitable[str | pathlib.Path],
    slurmrestd_charm: Awaitable[str | pathlib.Path],
    sackd_charm: Awaitable[str | pathlib.Path],
) -> None:
    """Test that the slurmctld charm can stabilize against slurmd, slurmdbd, slurmrestd, sackd, and MySQL."""
    logger.info(f"Deploying {', '.join(SLURM_APPS)}, and {DATABASE}")

    # Deploy the test Charmed SLURM cloud.
    await asyncio.gather(
        build_and_deploy_charm(
            ops_test,
            slurmctld_charm,
            application_name=SLURMCTLD,
            num_units=1,
            base=charm_base,
        ),
        build_and_deploy_charm(
            ops_test,
            slurmd_charm,
            application_name=SLURMD,
            num_units=1,
            base=charm_base,
        ),
        build_and_deploy_charm(
            ops_test,
            slurmdbd_charm,
            application_name=SLURMDBD,
            num_units=1,
            base=charm_base,
        ),
        build_and_deploy_charm(
            ops_test,
            slurmrestd_charm,
            application_name=SLURMRESTD,
            num_units=1,
            base=charm_base,
        ),
        build_and_deploy_charm(
            ops_test,
            sackd_charm,
            application_name=SACKD,
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
        ops_test.model.deploy(
            INFLUXDB,
            application_name=INFLUXDB,
            channel="latest/stable",
            num_units=1,
            base="ubuntu@20.04",
        ),
    )
    # Set integrations for charmed applications.
    await ops_test.model.integrate(f"{SLURMCTLD}:{SLURMD}", f"{SLURMD}:{SLURMCTLD}")
    await ops_test.model.integrate(f"{SLURMCTLD}:{SLURMDBD}", f"{SLURMDBD}:{SLURMCTLD}")
    await ops_test.model.integrate(f"{SLURMCTLD}:{SLURMRESTD}", f"{SLURMRESTD}:{SLURMCTLD}")
    await ops_test.model.integrate(f"{SLURMCTLD}:login-node", f"{SACKD}:{SLURMCTLD}")
    # await ops_test.model.integrate(f"{SLURMDBD}-{ROUTER}:backend-database", f"{DATABASE}:database")
    await ops_test.model.integrate(f"{SLURMDBD}:database", f"{DATABASE}:database")
    await ops_test.model.integrate(f"{SLURMCTLD}:influxdb", f"{INFLUXDB}:query")
    # Reduce the update status frequency to accelerate the triggering of deferred events.
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=SLURM_APPS + [INFLUXDB], status="active", timeout=1000
        )
        for app in SLURM_APPS + [INFLUXDB]:
            assert ops_test.model.applications[app].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
@pytest.mark.order(2)
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

    logger.info(
        f"Checking that the prometheus-slurm-exporter service is active inside the {SLURMCTLD} unit."
    )
    slurmctld = ops_test.model.applications[SLURMCTLD].units[0]
    res = (await slurmctld.ssh("systemctl is-active prometheus-slurm-exporter")).strip("\n")
    assert res == "active"


@pytest.mark.abort_on_fail
@pytest.mark.order(3)
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
@pytest.mark.order(4)
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


@pytest.mark.abort_on_fail
@pytest.mark.order(5)
@tenacity.retry(
    wait=tenacity.wait.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(3),
    reraise=True,
)
async def test_new_node_state_and_reason(ops_test: OpsTest) -> None:
    """Test that new nodes join the cluster in a down state and with an appropriate reason."""
    logger.info("Testing new slurmd unit is down with reason: 'New node.'")

    sackd_unit = ops_test.model.applications[SACKD].units[0]
    slurmd_node_state_reason = await sackd_unit.ssh(
        "sinfo -R | awk '{print $1, $2}' | sed 1d | tr -d '\n'"
    )
    slurmd_node_state = await sackd_unit.ssh("sinfo | awk '{print $5}' | sed 1d | tr -d '\n'")

    assert slurmd_node_state_reason == "New node."
    assert slurmd_node_state == "down"


@pytest.mark.abort_on_fail
@pytest.mark.order(6)
@tenacity.retry(
    wait=tenacity.wait.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(3),
    reraise=True,
)
async def test_node_configured_action(ops_test: OpsTest) -> None:
    """Test that the node-configured charm action makes slurmd unit 'idle'."""
    logger.info("Testing node-configured charm actions makes node status 'idle'.")

    slurmd_unit = ops_test.model.applications[SLURMD].units[0]
    action = await slurmd_unit.run_action("node-configured")
    action = await action.wait()

    sackd_unit = ops_test.model.applications[SACKD].units[0]
    slurmd_node_state = await sackd_unit.ssh("sinfo | awk '{print $5}' | sed 1d | tr -d '\n'")
    assert slurmd_node_state == "idle"


@pytest.mark.abort_on_fail
@pytest.mark.order(7)
@tenacity.retry(
    wait=tenacity.wait.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(3),
    reraise=True,
)
async def test_health_check_program(ops_test: OpsTest) -> None:
    """Test that running the HealthCheckProgram doesn't put the node in a drain state."""
    logger.info("Test running node health check doesn't drain node.")

    slurmd_unit = ops_test.model.applications[SLURMD].units[0]
    _ = await slurmd_unit.ssh("sudo /usr/sbin/charmed-hpc-nhc-wrapper")

    sackd_unit = ops_test.model.applications[SACKD].units[0]
    slurmd_node_state = await sackd_unit.ssh("sinfo | awk '{print $5}' | sed 1d | tr -d '\n'")
    assert slurmd_node_state == "idle"


@pytest.mark.abort_on_fail
@pytest.mark.order(8)
@tenacity.retry(
    wait=tenacity.wait.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(3),
    reraise=True,
)
async def test_job_submission_works(ops_test: OpsTest) -> None:
    """Test that a job can be submitted to the cluster."""
    logger.info("Test a simple job to get the hostname of the compute node.")

    # Get the hostname of the compute node via ssh
    slurmd_unit = ops_test.model.applications[SLURMD].units[0]
    res_from_ssh = await slurmd_unit.ssh("hostname -s")

    # Get the hostname of the compute node from slurm job
    sackd_unit = ops_test.model.applications[SACKD].units[0]
    res_from_slurm_job = await sackd_unit.ssh("srun -pslurmd hostname -s")
    assert res_from_ssh == res_from_slurm_job


@pytest.mark.abort_on_fail
@pytest.mark.order(9)
@tenacity.retry(
    wait=tenacity.wait.wait_exponential(multiplier=2, min=1, max=30),
    stop=tenacity.stop_after_attempt(3),
    reraise=True,
)
async def test_task_accounting_works(ops_test: OpsTest) -> None:
    """Test that influxdb is recording task level info."""
    logger.info("Test that influxdb is recording task level info.")
    sackd_unit = ops_test.model.applications[SACKD].units[0]
    _ = await sackd_unit.scp_to(
        "tests/integration/assets/sbatch_sleep_job.sh", "/home/ubuntu/sbatch_sleep_job.sh"
    )
    _ = await sackd_unit.ssh("sbatch /home/ubuntu/sbatch_sleep_job.sh")
    res = await sackd_unit.ssh("sstat 2 --format=NTasks --noheader | awk '{print $1}'")
    # Validate that sstat shows 1 task running
    assert int(res) == 1
