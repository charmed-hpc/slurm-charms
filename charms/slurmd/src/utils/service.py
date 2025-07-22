#!/usr/bin/python3
# Copyright 2023-2024 Canonical Ltd.
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

"""Manage the internal slurmd daemon on Juju machines.

This module also provides a wrapper for starting the slurmd service using systemd.
"""

import datetime
import logging
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import charms.operator_libs_linux.v1.systemd as systemd

_logger = logging.getLogger(__name__)


def override_service() -> None:
    """Override the default slurmd systemd service file.

    Notes:
        This method makes an invokes `systemd daemon-reload` after writing
        the overrides.conf file for slurmd. This invocation will reload
        all systemd units on the machine.
    """
    _logger.debug("Overriding default slurmd service file")
    if not (override_dir := Path("/etc/systemd/system/slurmd.service.d")).is_dir():
        override_dir.mkdir()

    overrides = override_dir / "99-slurmd-charm.conf"
    overrides.write_text(
        textwrap.dedent(
            f"""
            [Unit]
            ConditionPathExists=

            [Service]
            Type=forking
            Environment="PYTHONPATH={Path.cwd() / "lib"}"
            ExecStart=
            ExecStart=/usr/bin/python3 {__file__}
            LimitMEMLOCK=infinity
            LimitNOFILE=1048576
            TimeoutSec=900
            """
        ).strip()
    )
    systemd.daemon_reload()


def _start_slurmd_service() -> None:
    """Start the slurmd service on machine.

    This method is invoked when the slurmd utils module is executed as a runnable
    script. The method wraps the command traditionally executed by systemd when
    the slurmd service is started with `systemctl start slurmd`. The difference
    is that this method attempts to start the slurmd daemon over the course of
    15 minutes since the slurm.conf file may not be ready on the slurmctld server.
    """
    # Environment variables must be expanded here because the Popen
    # command will fail to execute if the inline environment variable
    # has a whitespace-delimited value. $SLURMD_OPTIONS is white-space
    # delimited, so it is expanded here to simplify the call to Popen.
    slurmd_cmd = shlex.split(os.path.expandvars("/usr/sbin/slurmd -D -s $SLURMD_OPTIONS"))

    # Try to start slurmd with ~5 seconds in-between each attempt. Timeout after 15 minutes.
    end_time = datetime.datetime.now() + datetime.timedelta(minutes=15)
    while True:
        if datetime.datetime.now() >= end_time:
            _logger.error("Failed to start slurmd daemon. Timeout exceeded")
            sys.exit(1)
        else:
            try:
                process = subprocess.Popen(slurmd_cmd, env=os.environ)
                # There needs to be a slight delay here to give slurmd
                # enough time to fail if configuration file is not ready yet.
                # If timeout is reached, this means the slurmd is running.
                # If exit code is returned, this means slurmd failed and is not running.
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _logger.info("Slurmd successfully started")
                break


if __name__ == "__main__":  # pragma: nocover
    _start_slurmd_service()
