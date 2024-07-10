# Copyright 2020-2024 Omnivector, LLC.
"""SlurmdbdOpsManager."""
import logging
import os
import subprocess
import textwrap
from datetime import datetime
from grp import getgrnam
from pwd import getpwnam
from typing import Optional

from constants import (
    JWT_RSA_PATH,
    SLURM_GROUP,
    SLURM_USER,
    SLURMDBD_CONF_PATH,
    SLURMDBD_DEFAULTS_FILE,
)

import charms.operator_libs_linux.v1.systemd as systemd
from charms.hpc_libs.v0.slurm_ops import ServiceType, SlurmManagerBase

logger = logging.getLogger()


class SlurmdbdManager(SlurmManagerBase):
    """Manage slurmdbd service operations."""

    def __init__(self) -> None:
        super().__init__(service=ServiceType.SLURMDBD)


class LegacySlurmdbdManager:
    """Legacy slurmdbd ops manager."""

    def write_slurmdbd_conf(self, slurmdbd_parameters: dict) -> None:
        """Render slurmdbd.conf."""
        slurm_user_uid = getpwnam(SLURM_USER).pw_uid
        slurm_group_gid = getgrnam(SLURM_GROUP).gr_gid

        header = textwrap.dedent(
            f"""
            #
            # {SLURMDBD_CONF_PATH} generated at {datetime.now()}
            #

            """
        )
        SLURMDBD_CONF_PATH.write_text(
            header + "\n".join([f"{k}={v}" for k, v in slurmdbd_parameters.items() if v != ""])
        )

        SLURMDBD_CONF_PATH.chmod(0o600)
        os.chown(f"{SLURMDBD_CONF_PATH}", slurm_user_uid, slurm_group_gid)

    def write_jwt_rsa(self, jwt_rsa: str) -> None:
        """Write the jwt_rsa key and set permissions."""
        slurm_user_uid = getpwnam(SLURM_USER).pw_uid
        slurm_group_gid = getgrnam(SLURM_GROUP).gr_gid

        JWT_RSA_PATH.write_text(jwt_rsa)
        JWT_RSA_PATH.chmod(0o600)

        os.chown(f"{JWT_RSA_PATH}", slurm_user_uid, slurm_group_gid)

    def check_munged(self) -> bool:
        """Check if munge is working correctly."""
        if not systemd.service_running("snap.slurm.munged"):
            return False

        output = ""
        # check if munge is working, i.e., can use the credentials correctly
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

    # Originally contributed by @wolsen
    # https://github.com/charmed-hpc/slurmdbd-operator/commit/2b47acda7f51aea8699886c49783eaf0de691747
    @classmethod
    def set_environment_var(cls, **kwargs: Optional[str]):
        """Update the environment settings in the /etc/defaults/slurmdbd file.

        Updates the slurmdbd defaults environment file to add the specified
        defaults. For example, to add the MY_VAR environment variable invoke with

            self._update_defaults(my_var="foobar")

        The key will be converted to all uppercase prior to being written to
        the specified file. To remove a setting, specify the value as None, e.g.:

            self._update_defaults(my_var=None)

        Note: variable names will be converted to upper case when being written
        to the file and for comparison of keys.

        Args:
            **kwargs:
                The environment variables that should be set or unset. The key
                will be upper-cased for the environment variable.
        """
        with open(SLURMDBD_DEFAULTS_FILE, "w+") as f:
            updated_contents = []

            keys_processed = set()

            for line in f.readlines():
                # Lines beginning with a hash are a comment. Don't process these
                # but do add the line to the output buffer to preserve it.
                if line.startswith("#"):
                    updated_contents.append(line)
                    continue

                # Attempt to get the environment variable and split it on the =.
                # If the line doesn't have an equals, then don't process the line
                # but do add the line to the output buffer to preserve it.
                line_parts = line.split("=", 1)
                if len(line_parts) < 2:
                    updated_contents.append(line)
                    continue

                var_name = line_parts[0].lower()
                if var_name not in kwargs:
                    updated_contents.append(line)
                    continue

                keys_processed.add(var_name)
                # If explicitly None, then remove from the output buffer as
                # the demand is to unset the variable.
                if kwargs[var_name] is None:
                    continue

                updated_contents.append(f"{var_name.upper()}={kwargs[var_name]}\n")

            for key, value in kwargs.items():
                # Skip any keys already processed.
                if key in keys_processed:
                    continue
                updated_contents.append(f"{key.upper()}={value}\n")

            f.seek(0)
            f.truncate()
            f.writelines(updated_contents)
