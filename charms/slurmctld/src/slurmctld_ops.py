# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.
"""This module provides the SlurmctldManager."""

import logging
import os
import socket
import subprocess
import tempfile
from base64 import b64decode, b64encode
from grp import getgrnam
from pathlib import Path
from pwd import getpwnam

import distro
from constants import SLURM_GROUP, SLURM_USER, UBUNTU_HPC_PPA_KEY
from Crypto.PublicKey import RSA
from slurm_conf_editor import slurm_conf_as_string

import charms.operator_libs_linux.v0.apt as apt
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


class SlurmctldManagerError(BaseException):
    """Exception for use with SlurmctldManager."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class CharmedHPCPackageLifecycleManager:
    """Facilitate ubuntu-hpc slurm component package lifecycles."""

    def __init__(self, package_name: str):
        self._package_name = package_name
        self._keyring_path = Path(f"/usr/share/keyrings/ubuntu-hpc-{self._package_name}.asc")

    def _repo(self) -> apt.DebianRepository:
        """Return the ubuntu-hpc repo."""
        ppa_url: str = "https://ppa.launchpadcontent.net/ubuntu-hpc/slurm-wlm-23.02/ubuntu"
        sources_list: str = (
            f"deb [signed-by={self._keyring_path}] {ppa_url} {distro.codename()} main"
        )
        return apt.DebianRepository.from_repo_line(sources_list)

    def install(self) -> bool:
        """Install package using lib apt."""
        package_installed = False

        if self._keyring_path.exists():
            self._keyring_path.unlink()
        self._keyring_path.write_text(UBUNTU_HPC_PPA_KEY)

        repositories = apt.RepositoryMapping()
        repositories.add(self._repo())

        try:
            apt.update()
            apt.add_package([self._package_name])
            package_installed = True
        except apt.PackageNotFoundError:
            logger.error(f"'{self._package_name}' not found in package cache or on system.")
        except apt.PackageError as e:
            logger.error(f"Could not install '{self._package_name}'. Reason: {e.message}")

        return package_installed

    def uninstall(self) -> None:
        """Uninstall the package using libapt."""
        if apt.remove_package(self._package_name):
            logger.info(f"'{self._package_name}' removed from system.")
        else:
            logger.error(f"'{self._package_name}' not found on system.")

        repositories = apt.RepositoryMapping()
        repositories.disable(self._repo())

        if self._keyring_path.exists():
            self._keyring_path.unlink()

    def upgrade_to_latest(self) -> None:
        """Upgrade package to latest."""
        try:
            slurm_package = apt.DebianPackage.from_system(self._package_name)
            slurm_package.ensure(apt.PackageState.Latest)
            logger.info(f"Updated '{self._package_name}' to: {slurm_package.version.number}.")
        except apt.PackageNotFoundError:
            logger.error(f"'{self._package_name}' not found in package cache or on system.")
        except apt.PackageError as e:
            logger.error(f"Could not install '{self._package_name}'. Reason: {e.message}")

    def version(self) -> str:
        """Return the package version."""
        slurm_package_vers = ""
        try:
            slurm_package_vers = apt.DebianPackage.from_installed_package(
                self._package_name
            ).version.number
        except apt.PackageNotFoundError:
            logger.error(f"'{self._package_name}' not found on system.")
        return slurm_package_vers


class SlurmctldManager:
    """SlurmctldManager."""

    def __init__(self):
        self._munge_package = CharmedHPCPackageLifecycleManager("munge")
        self._slurmctld_package = CharmedHPCPackageLifecycleManager("slurmctld")

    def install(self) -> bool:
        """Install slurmctld and munge to the system."""
        if self._slurmctld_package.install() is not True:
            return False
        systemd.service_stop("slurmctld")

        if self._munge_package.install() is not True:
            return False
        systemd.service_stop("munge")

        spool_dir = Path("/var/spool/slurmctld")
        if not spool_dir.exists():
            spool_dir.mkdir()

        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()
        os.chown(f"{spool_dir}", slurm_user_uid, slurm_group_gid)

        return True

    def version(self) -> str:
        """Return slurm version."""
        return self._slurmctld_package.version()

    def slurm_cmd(self, command, arg_string) -> None:
        """Run a slurm command."""
        try:
            subprocess.call([f"{command}"] + arg_string.split())
        except subprocess.CalledProcessError as e:
            raise (e)
            logger.error(f"Error running {command} - {e}")

    def write_slurm_conf(self, slurm_conf: dict) -> None:
        """Render the context to a template, adding in common configs."""
        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()

        target = Path("/etc/slurm/slurm.conf")
        target.write_text(slurm_conf_as_string(slurm_conf))

        os.chown(f"{target}", slurm_user_uid, slurm_group_gid)

    def write_munge_key(self, munge_key: str) -> None:
        """Base64 decode and write the munge key."""
        munge_user_uid = getpwnam("munge").pw_uid
        munge_group_gid = getgrnam("munge").gr_gid

        target = Path("/etc/munge/munge.key")
        target.write_bytes(b64decode(munge_key.encode()))

        target.chmod(0o600)
        os.chown(f"{target}", munge_user_uid, munge_group_gid)

    def write_jwt_rsa(self, jwt_rsa: str) -> None:
        """Write the jwt_rsa key."""
        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()

        target = Path("/var/spool/slurmctld/jwt_hs256.key")
        target.write_text(jwt_rsa)

        target.chmod(0o600)
        os.chown(f"{target}", slurm_user_uid, slurm_group_gid)

    def write_cgroup_conf(self, cgroup_conf: str) -> None:
        """Write the cgroup.conf file."""
        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()

        target = Path("/etc/slurm/cgroup.conf")
        target.write_text(cgroup_conf)

        target.chmod(0o600)
        os.chown(f"{target}", slurm_user_uid, slurm_group_gid)

    def generate_jwt_rsa(self) -> str:
        """Generate the rsa key to encode the jwt with."""
        return RSA.generate(2048).export_key("PEM").decode()

    def generate_munge_key(self) -> str:
        """Generate the munge.key."""
        munge_key_as_string = ""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_munge_key = Path(tmp_dir) / "munge.key"
            subprocess.check_call(["mungekey", "-c", "-k", tmp_munge_key, "-b", "2048"])
            munge_key_as_string = b64encode(tmp_munge_key.read_bytes()).decode()
        return munge_key_as_string

    def get_munge_key(self) -> str:
        """Read the bytes, encode to base64, decode to a string, return."""
        munge_key = Path("/etc/munge/munge.key").read_bytes()
        return b64encode(munge_key).decode()

    def stop_slurmctld(self) -> None:
        """Stop slurmctld service."""
        systemd.service_stop("slurmctld")

    def start_slurmctld(self) -> None:
        """Start slurmctld service."""
        systemd.service_start("slurmctld")

    def stop_munged(self) -> None:
        """Stop munge."""
        systemd.service_stop("munge")

    def start_munged(self) -> bool:
        """Start the munged process.

        Return True on success, and False otherwise.
        """
        logger.debug("Starting munge.")
        try:
            systemd.service_start("munge")
        # Ignore pyright error for is not a valid exception class, reportGeneralTypeIssues
        except SlurmctldManagerError(
            "Cannot start munge."
        ) as e:  # pyright: ignore [reportGeneralTypeIssues]
            logger.error(e)
            return False
        return self.check_munged()

    def check_munged(self) -> bool:
        """Check if munge is working correctly."""
        if not systemd.service_running("munge"):
            return False

        output = ""
        # check if munge is working, i.e., can use the credentials correctly
        try:
            logger.debug("## Testing if munge is working correctly")
            munge = subprocess.Popen(
                ["munge", "-n"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            if munge is not None:
                unmunge = subprocess.Popen(
                    ["unmunge"], stdin=munge.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE
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
