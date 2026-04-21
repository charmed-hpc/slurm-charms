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
def test_slurm_metrics_are_accessible(juju: jubilant.Juju) -> None:
    """Test that the `prometheus-slurm-exporter` service is active within `controller/0`."""
    unit = f"{SLURMCTLD_APP_NAME}/0"

    logger.info(
        "testing that the 'slurmctld' metrics endpoint is accessible on port 6817 on unit '%s'",
        unit,
    )
    result = juju.exec(
        "curl --silent --output /dev/null --write-out '%{http_code}\n' localhost:6817/metrics",
        unit=unit,
    )
    assert result.stdout.strip() == "200"


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
def test_default_slurmd_unit_node_state_and_reason(juju: jubilant.Juju) -> None:
    """Test that new nodes join the cluster in a down state and with an appropriate reason."""
    slurmd_unit = f"{SLURMD_APP_NAME}/0"
    name = slurmd_unit.replace("/", "-")

    logger.info("testing that a new slurmd unit is down with the reason: 'n/a'")
    result = json.loads(juju.exec(f"scontrol --json show node {name}", unit=slurmd_unit).stdout)
    assert "DOWN" in result["nodes"][0]["state"]
    assert result["nodes"][0]["reason"] == "'n/a'"


@pytest.mark.order(8)
def test_set_node_config_action(juju: jubilant.Juju) -> None:
    """Test that a compute node's configuration can be successfully updated."""
    slurmd_unit = f"{SLURMD_APP_NAME}/0"
    name = slurmd_unit.replace("/", "-")

    logger.info("testing that we can update the configuration of a single compute node")
    juju.run(slurmd_unit, "set-node-config", params={"parameters": "weight=100"})
    # Check that the weight of the compute node is 100.
    # Retry on failure as it may take a moment for scontrol output to update
    attempts = tenacity.Retrying(
        wait=tenacity.wait.wait_exponential(multiplier=2),
        stop=tenacity.stop_after_attempt(3),
        reraise=True,
    )
    for attempt in attempts:
        with attempt:
            result = json.loads(
                juju.exec(f"scontrol --json show node {name}", unit=slurmd_unit).stdout
            )
            assert result["nodes"][0]["weight"] == 100
            assert "DOWN" in result["nodes"][0]["state"]
            assert result["nodes"][0]["reason"] == "'n/a'"

    # Reset compute node to its default configuration.
    juju.run(slurmd_unit, "set-node-config", params={"reset": True})
    attempts = tenacity.Retrying(
        wait=tenacity.wait.wait_exponential(multiplier=2),
        stop=tenacity.stop_after_attempt(3),
        reraise=True,
    )
    for attempt in attempts:
        with attempt:
            result = json.loads(
                juju.exec(f"scontrol --json show node {name}", unit=slurmd_unit).stdout
            )
            assert result["nodes"][0]["weight"] == 1
            assert "DOWN" in result["nodes"][0]["state"]
            assert result["nodes"][0]["reason"] == "'n/a'"


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

    # Set state to 'idle'.
    juju.run(slurmctld_unit, "set-node-state", params={"nodes": name, "state": "idle"})
    result = json.loads(juju.exec(f"scontrol --json show node {name}", unit=slurmctld_unit).stdout)
    assert "IDLE" in result["nodes"][0]["state"]
    assert result["nodes"][0]["reason"] == ""


@pytest.mark.order(10)
def test_rotate_auth_key(juju: jubilant.Juju) -> None:
    """Test that the `rotate-auth-key` action updates the Slurm authentication key across the cluster."""
    slurmctld_unit = f"{SLURMCTLD_APP_NAME}/0"
    sackd_unit = f"{SACKD_APP_NAME}/0"
    slurmd_unit = f"{SLURMD_APP_NAME}/0"
    non_controller_units = [
        sackd_unit,
        slurmd_unit,
        f"{SLURMDBD_APP_NAME}/0",
        f"{SLURMRESTD_APP_NAME}/0",
    ]

    logger.info("testing that the `rotate-auth-key` action updates the Slurm authentication key")

    # Gather existing authentication key from controller unit.
    result = juju.exec("sudo cat /etc/slurm/slurm.jwks", unit=slurmctld_unit)
    initial_key_entry = json.loads(result.stdout)

    juju.run(slurmctld_unit, "rotate-auth-key")

    # Wait for action to complete and for all Slurm applications to return to ActiveStatus.
    juju.wait(
        lambda status: jubilant.all_active(status, *SLURM_APPS),
        error=lambda status: jubilant.any_error(status, *SLURM_APPS),
    )

    # Check authentication key has been updated on all units
    # Key rotation does not complete until the secret-remove event has completed on slurmctld. This
    # event is triggered after all observers have updated to the new secret revision. There may be
    # a gap where all Slurm applications are in ActiveStatus but secret-remove has not yet run so
    # the old key is still present on slurmctld. Account for this with tenacity.
    attempts = tenacity.Retrying(
        wait=tenacity.wait.wait_exponential(multiplier=2, min=1),
        stop=tenacity.stop_after_attempt(5),
        reraise=True,
    )
    for attempt in attempts:
        with attempt:
            result = juju.exec("sudo cat /etc/slurm/slurm.jwks", unit=slurmctld_unit)
            new_key_entry = json.loads(result.stdout)

            # Check old key removed from controller and new key present
            assert len(new_key_entry["keys"]) == 1
            assert new_key_entry != initial_key_entry

            # Check new key present on all other units
            for unit in non_controller_units:
                result = juju.exec("sudo cat /etc/slurm/slurm.jwks", unit=unit)
                key_entry = json.loads(result.stdout)
                assert len(key_entry["keys"]) == 1
                assert key_entry == new_key_entry, f"auth key rotation failed on: {unit}"

            # Check units can communicate with controller
            assert juju.exec("sinfo", unit=sackd_unit).success
            assert juju.exec("sinfo", unit=slurmd_unit).success
            # Database and API do not have client tools installed. Query from the controller
            assert juju.exec("sacct", unit=slurmctld_unit).success
            assert juju.exec("scontrol token", unit=slurmctld_unit).success


def _api_get(juju: jubilant.Juju, unit: str, token: str, url: str) -> tuple[str, str]:
    """Execute an authenticated GET against the Slurm REST API and return (status_code, body)."""
    result = juju.exec(
        f"export '{token}';"
        f" curl --silent --show-error"
        f" --write-out '\nHTTP_RESPONSE_CODE:%{{http_code}}'"
        f" --header X-SLURM-USER-TOKEN:$SLURM_JWT"
        f" --request GET '{url}'",
        unit=unit,
    )
    assert (
        "HTTP_RESPONSE_CODE:" in result.stdout
    ), f"no status code in response, stdout: {result.stdout} stderr: {result.stderr}"
    body, status_line = result.stdout.strip().rsplit("HTTP_RESPONSE_CODE:", 1)
    return status_line.strip(), body


@pytest.mark.order(11)
def test_rotate_jwt_key(juju: jubilant.Juju) -> None:
    """Test that the `rotate-jwt-key` action updates the Slurm JSON Web Token key across the cluster."""
    slurmctld_unit = f"{SLURMCTLD_APP_NAME}/0"
    slurmdbd_unit = f"{SLURMDBD_APP_NAME}/0"
    slurmrestd_unit = f"{SLURMRESTD_APP_NAME}/0"
    query_endpoint = "openapi"

    logger.info("testing that the `rotate-jwt-key` action updates the JSON Web Token key")

    # Confirm existing key on controller and database identical and functional before rotation.
    cat_cmd = "sudo cat /etc/slurm/jwt_hs256.key"
    initial_key_controller = juju.exec(cat_cmd, unit=slurmctld_unit).stdout
    initial_key_database = juju.exec(cat_cmd, unit=slurmdbd_unit).stdout
    assert (
        initial_key_controller == initial_key_database
    ), "initial JWT key on controller and database differ"

    # Use sudo to generate token to ensure access to all API endpoints.
    initial_token = juju.exec(
        "sudo scontrol token lifespan=infinite", unit=slurmctld_unit
    ).stdout.strip()

    # Query for list of all API endpoints.
    address = juju.status().apps[SLURMRESTD_APP_NAME].units[slurmrestd_unit].public_address
    base_url = f"http://{address}:6820"
    status_code, body = _api_get(
        juju, slurmctld_unit, initial_token, f"{base_url}/{query_endpoint}"
    )
    assert status_code == "200", f"failed to query API with initial JWT key, got body: {body}"
    endpoints = json.loads(body)
    assert "paths" in endpoints, f"initial API response missing 'paths', got: {body}"

    # Find slurm and slurmdbd diagnostic endpoints.
    # Example: "/slurm/v0.0.41/diag/" and "/slurmdb/v0.0.41/diag/".
    all_paths = endpoints["paths"].keys()
    slurm_diag = next(
        (p for p in all_paths if p.startswith("/slurm/") and p.endswith("/diag/")), None
    )
    slurmdb_diag = next(
        (p for p in all_paths if p.startswith("/slurmdb/") and p.endswith("/diag/")), None
    )
    assert slurm_diag is not None, "failed to find slurm diagnostic endpoint"
    assert slurmdb_diag is not None, "failed to find slurmdb diagnostic endpoint"

    # Query diagnostic endpoints to confirm initial token validity.
    diag_urls = [f"{base_url}{slurm_diag}", f"{base_url}{slurmdb_diag}"]
    for url in diag_urls:
        status_code, body = _api_get(juju, slurmctld_unit, initial_token, url)
        assert status_code == "200", f"initial JWT key not functional at {url}, got body: {body}"

    juju.run(slurmctld_unit, "rotate-jwt-key")

    # Wait for action to complete and for all Slurm applications to return to ActiveStatus.
    juju.wait(
        lambda status: jubilant.all_active(status, *SLURM_APPS),
        error=lambda status: jubilant.any_error(status, *SLURM_APPS),
    )

    # Poll until old key removed and new key present.
    attempts = tenacity.Retrying(
        wait=tenacity.wait.wait_exponential(multiplier=2, min=1),
        stop=tenacity.stop_after_attempt(5),
        reraise=True,
    )
    for attempt in attempts:
        with attempt:
            new_key_controller = juju.exec(cat_cmd, unit=slurmctld_unit).stdout
            new_key_database = juju.exec(cat_cmd, unit=slurmdbd_unit).stdout
            assert (
                new_key_controller != initial_key_controller
            ), "JWT key not rotated on controller"
            assert (
                new_key_controller == new_key_database
            ), "JWT key on controller and database differ after rotation"

    # Check old token no longer functional after rotation.
    status_code, _ = _api_get(juju, slurmctld_unit, initial_token, diag_urls[0])
    assert status_code != "200", f"old token still valid after rotation (HTTP {status_code})"

    # Check new key functional.
    new_token = juju.exec(
        "sudo scontrol token lifespan=infinite", unit=slurmctld_unit
    ).stdout.strip()
    for url in diag_urls:
        status_code, body = _api_get(juju, slurmctld_unit, new_token, url)
        assert status_code == "200", f"new JWT key not functional at {url}, got body: {body}"


@pytest.mark.order(12)
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


@pytest.mark.order(13)
def test_gpu_job_submission(juju: jubilant.Juju) -> None:
    """Test that a job requesting a GPU can be successfully submitted to the Slurm cluster.

    Warnings:
       - This test has been validated with Slurm 25.11 and its NVIDIA GPU autodetection plugin.
         Functionality is not guaranteed with other versions of Slurm.
    """
    sackd_unit = f"{SACKD_APP_NAME}/0"
    slurmd_unit = f"{SLURMD_APP_NAME}/0"
    name = slurmd_unit.replace("/", "-")

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
    gpu_information = textwrap.dedent("""\
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
        """)
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
    juju.run(slurmd_unit, "set-node-config", {"parameters": "gres=gpu:mock_gpu:1"})

    # Temporarily disable constrained devices to avoid cgroup errors in the test LXD containers
    juju.config(SLURMCTLD_APP_NAME, values={"cgroup-parameters": "constraindevices=no"})

    # Re-register the node to pick up the new GPU
    slurmd_result = juju.exec("hostname -s", unit=slurmd_unit)
    logger.info("re-registering slurmd node '%s' to set up mock GPU", name)
    juju.exec(f"sudo scontrol delete nodename={name}", unit=sackd_unit)
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
    cleanup_commands = [
        "sudo umount /sys/bus/pci/drivers",
        "sudo umount /proc/driver",
        "sudo umount /dev/nvidia0",
        "sudo rm -rf /tmp/sys",
        "sudo rm -rf /tmp/proc",
        "sudo rm -f /dev/nvidia0",
    ]
    for command in cleanup_commands:
        juju.exec(command, unit=slurmd_unit)
    juju.run(slurmd_unit, "set-node-config", {"reset": True})

    juju.config(SLURMCTLD_APP_NAME, reset="cgroup-parameters")
    juju.exec(f"sudo scontrol delete nodename={name}", unit=sackd_unit)
    juju.exec("sudo systemctl restart slurmd", unit=slurmd_unit)
