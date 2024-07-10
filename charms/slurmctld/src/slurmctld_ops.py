# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.

"""This module provides the SlurmctldManager."""

import logging
import os
import socket
import subprocess
from grp import getgrnam
from pwd import getpwnam

from constants import CGROUP_CONF_PATH, JWT_KEY_PATH, SLURM_CONF_PATH, SLURM_GROUP, SLURM_USER
from Crypto.PublicKey import RSA
from slurm_conf_editor import slurm_conf_as_string

import charms.operator_libs_linux.v1.systemd as systemd

logger = logging.getLogger()


def is_container() -> bool:
    """Determine if we are running in a container."""
    container = False
    try:
        container = subprocess.call(["systemd-detect-virt", "--container"]) == 0
    except subprocess.CalledProcessError as e:
        logger.error(e)
        raise (e)
    return container


def _get_slurm_user_uid_and_slurm_group_gid():
    """Return the slurm user uid and slurm group gid."""
    slurm_user_uid = getpwnam(SLURM_USER).pw_uid
    slurm_group_gid = getgrnam(SLURM_GROUP).gr_gid
    return slurm_user_uid, slurm_group_gid


class LegacySlurmctldManager:
    """Legacy slurmctld ops manager."""

    def write_slurm_conf(self, slurm_conf: dict) -> None:
        """Render the context to a template, adding in common configs."""
        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()

        SLURM_CONF_PATH.write_text(slurm_conf_as_string(slurm_conf))

        os.chown(f"{SLURM_CONF_PATH}", slurm_user_uid, slurm_group_gid)

    def write_jwt_rsa(self, jwt_rsa: str) -> None:
        """Write the jwt_rsa key."""
        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()
        JWT_KEY_PATH.write_text(jwt_rsa)
        JWT_KEY_PATH.chmod(0o600)
        os.chown(f"{JWT_KEY_PATH}", slurm_user_uid, slurm_group_gid)

    def write_cgroup_conf(self, cgroup_conf: str) -> None:
        """Write the cgroup.conf file."""
        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()
        CGROUP_CONF_PATH.write_text(cgroup_conf)
        CGROUP_CONF_PATH.chmod(0o600)
        os.chown(f"{CGROUP_CONF_PATH}", slurm_user_uid, slurm_group_gid)

    def generate_jwt_rsa(self) -> str:
        """Generate the rsa key to encode the jwt with."""
        return RSA.generate(2048).export_key("PEM").decode()

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

    @property
    def hostname(self) -> str:
        """Return the hostname."""
        return socket.gethostname().split(".")[0]
