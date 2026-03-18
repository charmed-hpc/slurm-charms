#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
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

"""Slurm email notification tests."""

import logging
import re
import socket
from email import message_from_string, policy
from email.message import EmailMessage

import jubilant
import pytest
import tenacity
from aiosmtpd.controller import Controller
from constants import (
    NETWORK_INTERFACE,
    SACKD_APP_NAME,
    SLURMCTLD_APP_NAME,
    SLURMD_APP_NAME,
    SMTP_INTEGRATOR_APP_NAME,
    SMTP_SERVER_PORT,
)
from psutil import net_if_addrs

logger = logging.getLogger(__name__)


class Handler:
    """SMTP server handler to capture sent test emails."""

    def __init__(self):
        self.latest_email = EmailMessage()

    async def handle_DATA(self, server, session, envelope):  # noqa: N802
        mail_string = envelope.content.decode("utf8", errors="replace")
        self.latest_email = message_from_string(mail_string, policy=policy.default)
        return "250 Message accepted for delivery"

    # Retry to account for mail spooling time
    @tenacity.retry(
        wait=tenacity.wait.wait_fixed(10),
        stop=tenacity.stop_after_attempt(10),
        reraise=True,
    )
    def assert_mail(self, expected_to: str, subject_pattern: str, content_pattern: str):
        """Assert received email matches expected recipient, subject regex, and body regex."""
        self.assert_to(expected_to)
        self.assert_subject(subject_pattern)
        self.assert_content(content_pattern)

    def assert_content(self, pattern: str):
        """Assert received email body matches the given regex."""
        # Email expected to be multipart - both plain text and HTML
        part_count = 0
        for part in self.latest_email.iter_parts():
            part_count += 1
            ctype = part.get_content_type()
            content = part.get_content()

            assert ctype in ("text/plain", "text/html"), f"Unexpected content type: {ctype}"
            assert re.search(pattern, content, re.DOTALL), f"Pattern not found in {ctype} part"

        assert part_count == 2, f"Expected 2 parts in email, found {part_count}"

    def assert_subject(self, pattern: str):
        """Assert received email subject line matches the given regex."""
        subject = self.latest_email["Subject"]
        assert re.match(pattern, subject), f"Subject '{subject}' doesn't match pattern '{pattern}'"

    def assert_to(self, expected_to: str):
        """Assert received email was sent to expected recipient."""
        actual_to = self.latest_email["To"]
        assert actual_to == expected_to, f"Expected recipient '{expected_to}', got '{actual_to}'"


def get_interface_ipv4(interface) -> str:
    """Get the IPv4 address of the given network interface.

    Raises:
        ValueError: if the interface name is invalid.
        RuntimeError: if an IP is not found on the interface.
    """
    interfaces = net_if_addrs()
    try:
        addrs = interfaces[interface]
    except KeyError as e:
        raise ValueError(
            f"Invalid interface: '{interface}'. Available interfaces: {list(interfaces.keys())}"
        ) from e

    for addr in addrs:
        if addr.family == socket.AF_INET:
            return addr.address

    raise RuntimeError(f"Interface '{interface}' exists but has no IPv4 address.")


@pytest.fixture(scope="module")
def smtp_handler():
    """Set up a local SMTP server."""
    handler = Handler()
    ip_address = get_interface_ipv4(NETWORK_INTERFACE)

    # Start SMTP server. Tests access emails through attribute of yielded handler
    controller = Controller(handler, hostname=ip_address, port=SMTP_SERVER_PORT)
    controller.start()

    yield handler

    controller.stop()


@pytest.mark.order(14)
def test_slurmctld_mail_deploy(juju: jubilant.Juju) -> None:
    """Test deployment and integration of SMTP integrator with slurmctld."""
    juju.deploy(
        "smtp-integrator",
        SMTP_INTEGRATOR_APP_NAME,
        config={"host": get_interface_ipv4(NETWORK_INTERFACE), "port": SMTP_SERVER_PORT},
    )
    juju.integrate(SLURMCTLD_APP_NAME, f"{SMTP_INTEGRATOR_APP_NAME}:smtp")

    juju.wait(
        lambda status: jubilant.all_active(status, SLURMCTLD_APP_NAME, SMTP_INTEGRATOR_APP_NAME)
    )


@pytest.mark.order(15)
def test_slurmctld_mail_job_end(juju: jubilant.Juju, smtp_handler) -> None:
    """Test notification email when a job ends successfully."""
    sackd_unit = f"{SACKD_APP_NAME}/0"
    to_address = "user@localhost"
    subject_pattern = r"^Job charmed-hpc-[\w-]{4}\.\d+: Ended$"
    content_pattern = r"Your job \d+ has ended on charmed-hpc-[\w-]{4}\."

    juju.exec(
        f"srun --time=1 --partition {SLURMD_APP_NAME} --mail-user={to_address} --mail-type=END sleep 1",
        unit=sackd_unit,
    )

    smtp_handler.assert_mail(to_address, subject_pattern, content_pattern)


@pytest.mark.order(16)
def test_slurmctld_mail_job_fail(juju: jubilant.Juju, smtp_handler) -> None:
    """Test notification email when a job fails."""
    sackd_unit = f"{SACKD_APP_NAME}/0"
    to_address = "anotheruser@localhost"
    subject_pattern = r"^Job charmed-hpc-[\w-]{4}\.\d+: Failed$"
    content_pattern = r"Your job \d+ has failed on charmed-hpc-[\w-]{4}\."

    try:
        juju.exec(
            f"srun --time=1 --partition {SLURMD_APP_NAME} --mail-user={to_address} --mail-type=FAIL,END bash -c 'sleep 1; exit 1'",
            unit=sackd_unit,
        )
    except jubilant.TaskError:
        # Ignore - failure is intentional to trigger an email
        pass

    smtp_handler.assert_mail(to_address, subject_pattern, content_pattern)


@pytest.mark.order(17)
def test_slurmctld_mail_job_begins_custom_signature(juju: jubilant.Juju, smtp_handler) -> None:
    """Test custom signature on a notification email when a job begins."""
    sackd_unit = f"{SACKD_APP_NAME}/0"
    to_address = "furtheruser@localhost"
    from_name = "Integration Test Suite"
    subject_pattern = r"^Job charmed-hpc-[\w-]{4}\.\d+: Began$"
    content_pattern = (
        r"Your job \d+ has started on charmed-hpc-[\w-]{4}\."
        r".*?"
        r"Regards,"
        r".*?"
        rf"{from_name}"
    )
    juju.config(SLURMCTLD_APP_NAME, {"email-from-name": from_name})

    juju.exec(
        f"srun --time=1 --partition {SLURMD_APP_NAME} --mail-user={to_address} --mail-type=BEGIN sleep 1",
        unit=sackd_unit,
    )

    smtp_handler.assert_mail(to_address, subject_pattern, content_pattern)


@pytest.mark.order(18)
def test_slurmctld_mail_remove(juju: jubilant.Juju) -> None:
    """Test SMTP integrator application removal and breaking of integration with slurmctld."""
    juju.remove_application(SMTP_INTEGRATOR_APP_NAME)
    juju.wait(
        lambda status: SMTP_INTEGRATOR_APP_NAME not in status.apps
        and jubilant.all_active(status, SLURMCTLD_APP_NAME)
    )


# TODO: Include mail test with HA once new Github runner is available and test suite is refactored
