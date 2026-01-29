#!/usr/bin/env python3
# Copyright 2023-2026 Canonical Ltd.
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

import json
import logging
import textwrap

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
def test_deploy(
    juju: jubilant.Juju, base, sackd, slurmctld, slurmd, slurmdbd, slurmrestd, fast_forward
) -> None:
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
    juju.wait(
        lambda status: jubilant.all_active(status, *SLURM_APPS),
        error=lambda status: jubilant.any_error(status, *SLURM_APPS),
    )


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
def test_set_node_config_action(juju: jubilant.Juju) -> None:
    """Test that a compute node's configuration can be successfully updated."""
    slurmd_unit = f"{SLURMD_APP_NAME}/0"
    name = slurmd_unit.replace("/", "-")

    logger.info("testing that we can update the configuration of a single compute node")
    juju.run(slurmd_unit, "set-node-config", params={"parameters": "weight=100"})
    # Check that the weight of the compute node is 100.
    result = json.loads(juju.exec(f"scontrol --json show node {name}", unit=slurmd_unit).stdout)
    assert result["nodes"][0]["weight"] == 100

    # Reset compute node to its default configuration.
    juju.run(slurmd_unit, "set-node-config", params={"reset": True})
    result = json.loads(juju.exec(f"scontrol --json show node {name}", unit=slurmd_unit).stdout)
    assert result["nodes"][0]["weight"] == 1


@pytest.mark.order(9)
def test_set_node_state(juju: jubilant.Juju) -> None:
    """Test that the `set-node-state` action updates the state of registered compute nodes."""
    slurmctld_unit = f"{SLURMCTLD_APP_NAME}/0"
    slurmd_unit = f"{SLURMD_APP_NAME}/0"
    name = slurmd_unit.replace("/", "-")

    logger.info("testing that the `set-node-state` action updates the state of compute nodes")
    # Set state of compute node to down with reason "Maintenance".
    juju.run(
        slurmctld_unit,
        "set-node-state",
        params={"nodes": name, "state": "down", "reason": "maintenance"},
    )
    # Check that the state of `slurmd/0` is 'down'.
    result = json.loads(juju.exec(f"scontrol --json show node {name}", unit=slurmctld_unit).stdout)
    assert "DOWN" in result["nodes"][0]["state"]
    assert result["nodes"][0]["reason"] == "'maintenance'"

    # Reset state to 'idle'.
    juju.run(slurmctld_unit, "set-node-state", params={"nodes": name, "state": "idle"})
    result = json.loads(juju.exec(f"scontrol --json show node {name}", unit=slurmctld_unit).stdout)
    assert "IDLE" in result["nodes"][0]["state"]
    assert result["nodes"][0]["reason"] == ""


@pytest.mark.order(10)
def test_job_submission(juju: jubilant.Juju) -> None:
    """Test that a job can be successfully submitted to the Slurm cluster."""
    sackd_unit = f"{SACKD_APP_NAME}/0"
    slurmd_unit = f"{SLURMD_APP_NAME}/0"

    logger.info("testing that a simple job can be submitted to slurm and successfully run")
    # Get the hostname of the compute node via `juju exec`.
    slurmd_result = juju.exec("hostname -s", unit=slurmd_unit)
    # Get the hostname of the compute node from a Slurm job.
    sackd_result = juju.exec(f"srun --partition {SLURMD_APP_NAME} hostname -s", unit=sackd_unit)
    assert sackd_result.stdout == slurmd_result.stdout


@pytest.mark.order(11)
def test_gpu_job_submission(juju: jubilant.Juju) -> None:
    """Test that a job requesting a GPU can be successfully submitted to the Slurm cluster.

    Warnings:
       - This test has been validated with Slurm 25.11 and its NVIDIA GPU autodetection plugin.
         Functionality is not guaranteed with other versions of Slurm.
    """
    sackd_unit = f"{SACKD_APP_NAME}/0"
    slurmd_unit = f"{SLURMD_APP_NAME}/0"

    # Set up a mock GPU device on the slurmd unit by mounting over relevant files in /sys and /proc
    # This is tightly coupled to the method the Slurm "Autodetect=nvidia" plugin uses to detect GPUs
    # Changes to that method in future Slurm revisions may break this test
    # Mock NUMA region info in /sys
    juju.exec("mkdir -p /tmp/sys/bus/pci/drivers/nvidia/0000:01:00.0/", unit=slurmd_unit)
    juju.exec(
        "cp /sys/devices/system/node/node0/cpulist /tmp/sys/bus/pci/drivers/nvidia/0000:01:00.0/local_cpulist",
        unit=slurmd_unit,
    )
    juju.exec(
        "sudo mount -t overlay overlay -o lowerdir=/sys/bus/pci/drivers:/tmp/sys/bus/pci/drivers /sys/bus/pci/drivers",
        unit=slurmd_unit,
    )

    # Mock GPU info in /proc
    gpu_information = textwrap.dedent(
        """\
            Model: 		 Mock GPU
            IRQ:   		 185
            GPU UUID: 	 GPU-12345678-90ab-cdef-1234-567890abcdef
            Video BIOS: 	 12.34.56.78.aa
            Bus Type: 	 PCIe
            DMA Size: 	 47 bits
            DMA Mask: 	 0x7fffffffffff
            Bus Location: 	 0000:01:00.0
            Device Minor: 	 0
            GPU Firmware: 	 123.456.78
            GPU Excluded:	 No
        """
    )
    juju.exec("mkdir -p /tmp/proc/driver/nvidia/gpus/0000:01:00.0/", unit=slurmd_unit)
    juju.exec(
        f"echo '{gpu_information}' > /tmp/proc/driver/nvidia/gpus/0000:01:00.0/information",
        unit=slurmd_unit,
    )
    # Can't overlay mount with /proc. Attempts fail with error:
    #   "wrong fs type, bad option, bad superblock on overlay, missing codepage or helper program, or other error"
    # Bind mount over the top instead. This should only block `/proc/driver/rtc` briefly
    juju.exec("sudo mount --bind /tmp/proc/driver /proc/driver", unit=slurmd_unit)

    # Slurm expects a GPU device file under /dev when auto-detecting GPUs.
    # Use /dev/zero as a mock by bind mounting over an empty /dev/nvidia0 device file.
    juju.exec("sudo touch /dev/nvidia0", unit=slurmd_unit)
    juju.exec("sudo mount --bind /dev/zero /dev/nvidia0", unit=slurmd_unit)

    # Manually add Gres line to dynamic node config. Necessary as the mock GPU was not present at
    # charm install time so was not auto-detected.
    juju.exec("sudo sed -i \"s/'$/ gres=gpu:mock_gpu:1'/\" /etc/default/slurmd", unit=slurmd_unit)

    # Temporarily disable constrained devices to avoid cgroup errors in the test LXD containers
    juju.config(SLURMCTLD_APP_NAME, values={"cgroup-parameters": "constraindevices=no"})

    # Re-register the node to pick up the new GPU
    slurmd_result = juju.exec("hostname -s", unit=slurmd_unit)
    slurmd_nodename = slurmd_result.stdout.strip()
    logger.info("re-registering slurmd node '%s' to set up mock GPU", slurmd_nodename)
    juju.exec(f"sudo scontrol delete NodeName={slurmd_nodename}", unit=sackd_unit)
    juju.exec("sudo systemctl restart slurmd", unit=slurmd_unit)

    logger.info("testing that a GPU job can be submitted to slurm and successfully run")

    # Retry on failure as it may take a moment for the node to re-register
    attempts = tenacity.Retrying(
        wait=tenacity.wait.wait_exponential(multiplier=2, min=1),
        stop=tenacity.stop_after_attempt(3),
        reraise=True,
    )
    for attempt in attempts:
        with attempt:
            sackd_result = juju.exec(
                f"srun --partition {SLURMD_APP_NAME} --gres gpu:1 hostname -s", unit=sackd_unit
            )
            assert sackd_result.stdout == slurmd_result.stdout

    logger.info("cleaning up mock GPU setup")
    juju.exec("sudo umount /sys/bus/pci/drivers", unit=slurmd_unit)
    juju.exec("sudo umount /proc/driver", unit=slurmd_unit)
    juju.exec("sudo umount /dev/nvidia0", unit=slurmd_unit)
    juju.exec("sudo rm -rf /tmp/sys", unit=slurmd_unit)
    juju.exec("sudo rm -rf /tmp/proc", unit=slurmd_unit)
    juju.exec("sudo rm -f /dev/nvidia0", unit=slurmd_unit)
    juju.exec("sudo sed -i \"s/ gres=gpu:mock_gpu:1'/'/\" /etc/default/slurmd", unit=slurmd_unit)
    juju.config(SLURMCTLD_APP_NAME, reset="cgroup-parameters")
    juju.exec(f"sudo scontrol delete NodeName={slurmd_nodename}", unit=sackd_unit)
    juju.exec("sudo systemctl restart slurmd", unit=slurmd_unit)
