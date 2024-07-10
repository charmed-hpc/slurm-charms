# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.
"""This module provides the SlurmrestdManager."""

import logging
import os
import subprocess

from constants import (
    SLURM_CONF_PATH,
    SLURMRESTD_GROUP_GID,
    SLURMRESTD_USER_UID,
)

import charms.hpc_libs.v0.slurm_ops as slurm
import charms.operator_libs_linux.v1.systemd as systemd
from charms.hpc_libs.v0.slurm_ops import ServiceType, SlurmManagerBase

logger = logging.getLogger()


class SlurmrestdManager(SlurmManagerBase):
    """Manage slurmrestd service operations."""

    def __init__(self) -> None:
        super().__init__(service=ServiceType.SLURMRESTD)

    def install(self) -> None:
        """Install slurmrestd and munge to the system."""
        logger.debug("## Installing and configuring slurm.")

        slurm.install()

        os.chown(f"{SLURM_CONF_PATH.parent}", SLURMRESTD_USER_UID, SLURMRESTD_GROUP_GID)


class SlurmrestdManagerError(BaseException):
    """Exception for use with SlurmrestdManager."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class LegacySlurmrestdManager:
    """Legacy slurmrestd ops manager."""

    def write_slurm_conf(self, slurm_conf: str) -> None:
        """Render /etc/slurm/slurm.conf."""
        logger.debug(f"Writing slurm.conf: {SLURM_CONF_PATH}")

        SLURM_CONF_PATH.write_text(slurm_conf)

        os.chown(f"{SLURM_CONF_PATH}", SLURMRESTD_USER_UID, SLURMRESTD_GROUP_GID)

    def check_munged(self) -> bool:
        """Check if munge is working correctly."""
        if not systemd.service_running("snap.slurm.munged"):
            return False

        # check if munge is working, i.e., can use the credentials correctly
        output = ""
        try:
            logger.debug("## Testing if munge is working correctly")
            munge = subprocess.Popen(
                ["slurm.munge", "-n"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if munge is not None:
                unmunge = subprocess.Popen(
                    ["slurm.unmunge"],
                    stdin=munge.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                output = unmunge.communicate()[0].decode()
            if "Success" in output:
                logger.debug(f"## Munge working as expected: {output}")
                return True
            logger.error(f"## Munge not working: {output}")
        except subprocess.CalledProcessError as e:
            logger.error(f"## Error testing munge: {e}")

        return False
