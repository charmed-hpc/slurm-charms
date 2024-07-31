# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.
"""This module provides the SlurmrestdManager."""

import logging
import os
import subprocess
from base64 import b64decode
from pathlib import Path

import distro
from constants import (
    MUNGE_KEY_PATH,
    SLURMRESTD_GROUP_GID,
    SLURMRESTD_GROUP_NAME,
    SLURMRESTD_SERVICE,
    SLURMRESTD_USER_NAME,
    SLURMRESTD_USER_UID,
    UBUNTU_HPC_PPA_KEY,
)

import charms.operator_libs_linux.v0.apt as apt
import charms.operator_libs_linux.v1.systemd as systemd

logger = logging.getLogger()


class SlurmrestdManagerError(BaseException):
    """Exception for use with SlurmrestdManager."""

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


class SlurmrestdManager:
    """SlurmrestdManager."""

    def __init__(self):
        self._munge_package = CharmedHPCPackageLifecycleManager("munge")
        self._slurmrestd_package = CharmedHPCPackageLifecycleManager("slurmrestd")
        self._slurm_plugins_package = CharmedHPCPackageLifecycleManager("slurm-wlm-basic-plugins")

    def install(self) -> bool:
        """Install slurmrestd and munge to the system."""
        logger.debug("Installing and configuring slurmrestd and munge packages.")

        if self._slurmrestd_package.install() is not True:
            return False
        systemd.service_stop("slurmrestd")

        if self._munge_package.install() is not True:
            return False
        systemd.service_stop("munge")

        if self._slurm_plugins_package.install() is not True:
            return False

        self._create_slurmrestd_user_group()

        slurm_conf_dir = Path("/etc/slurm")
        slurm_conf_dir.mkdir(exist_ok=True)

        os.chown(f"{slurm_conf_dir}", SLURMRESTD_USER_UID, SLURMRESTD_GROUP_GID)

        logger.debug("Replacing slurmrestd.service")
        target = Path("/usr/lib/systemd/system/slurmrestd.service")
        target.write_text(SLURMRESTD_SERVICE)
        systemd.daemon_reload()

        return True

    def version(self) -> str:
        """Return slurm version."""
        return self._slurmrestd_package.version()

    def write_slurm_conf(self, slurm_conf: str) -> None:
        """Render /etc/slurm/slurm.conf."""
        target = Path("/etc/slurm/slurm.conf")
        logger.debug(f"Writing slurm.conf: {target}")

        target.write_text(slurm_conf)

        os.chown(f"{target}", SLURMRESTD_USER_UID, SLURMRESTD_GROUP_GID)

    def write_munge_key(self, munge_key: str) -> None:
        """Base64 decode and write the munge key."""
        MUNGE_KEY_PATH.write_bytes(b64decode(munge_key.encode()))

    def check_munged(self) -> bool:
        """Check if munge is working correctly."""
        if not systemd.service_running("munge"):
            return False

        # check if munge is working, i.e., can use the credentials correctly
        output = ""
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

    def _create_slurmrestd_user_group(self) -> None:
        """Create the slurmrestd user."""
        logger.info("#### Creating slurmrestd user and group")

        try:
            subprocess.check_output(
                ["groupadd", "--gid", f"{SLURMRESTD_GROUP_GID}", f"{SLURMRESTD_GROUP_NAME}"]
            )
        except subprocess.CalledProcessError as e:
            if e.returncode == 9:
                logger.warning(f"Group '{SLURMRESTD_GROUP_NAME}' already exists.")
            else:
                logger.error(f"Error creating group: '{SLURMRESTD_GROUP_NAME}' - {e}")
                raise e

        try:
            subprocess.check_output(
                [
                    "adduser",
                    "--system",
                    "--gid",
                    f"{SLURMRESTD_GROUP_GID}",
                    "--uid",
                    f"{SLURMRESTD_USER_UID}",
                    "--no-create-home",
                    "--home",
                    "/nonexistent",
                    f"{SLURMRESTD_USER_NAME}",
                ]
            )
        except subprocess.CalledProcessError as e:
            if e.returncode == 9:
                logger.warning(f"User '{SLURMRESTD_USER_NAME}' already exists.")
            else:
                logger.error(f"Error creating user: '{SLURMRESTD_USER_NAME} - {e}")
                raise e

        logger.info("'{SLURMRESTD_USER_NAME}' user and '{SLURMRESTD_GROUP_NAME}' group created.")

    def stop_slurmrestd(self) -> None:
        """Stop slurmrestd service."""
        systemd.service_stop("slurmrestd")

    def start_slurmrestd(self) -> None:
        """Start slurmrestd service."""
        systemd.service_start("slurmrestd")

    def stop_munge(self) -> None:
        """Stop munge."""
        systemd.service_stop("munge")

    def start_munge(self) -> bool:
        """Start the munge process.

        Return True on success, and False otherwise.
        """
        logger.debug("Starting munge.")
        try:
            systemd.service_start("munge")
        # Ignore pyright error for is not a valid exception class, reportGeneralTypeIssues
        except SlurmrestdManagerError(
            "Cannot start munge."
        ) as e:  # pyright: ignore [reportGeneralTypeIssues]
            logger.error(e)
            return False
        return self.check_munged()
