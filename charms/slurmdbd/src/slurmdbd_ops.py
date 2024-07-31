# Copyright 2020-2024 Omnivector, LLC.
"""SlurmdbdOpsManager."""
import logging
import os
import socket
import subprocess
import textwrap
from base64 import b64decode
from datetime import datetime
from grp import getgrnam
from pathlib import Path
from pwd import getpwnam
from typing import Optional

import distro
from constants import (
    SLURM_GROUP,
    SLURM_USER,
    SLURMDBD_DEFAULTS_FILE,
    STATE_DIR,
    UBUNTU_HPC_PPA_KEY,
)

import charms.operator_libs_linux.v0.apt as apt
import charms.operator_libs_linux.v1.systemd as systemd

logger = logging.getLogger()


class SlurmdbdManagerError(BaseException):
    """Exception for use with SlurmdbdManager."""

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
        slurmdbd_vers = ""
        try:
            slurmdbd_vers = apt.DebianPackage.from_installed_package(
                self._package_name
            ).version.number
        except apt.PackageNotFoundError:
            logger.error(f"'{self._package_name}' not found on system.")
        return slurmdbd_vers


class SlurmdbdOpsManager:
    """SlurmdbdOpsManager."""

    def __init__(self):
        """Set the initial attribute values."""
        self._slurm_component = "slurmdbd"
        self._munge_package = CharmedHPCPackageLifecycleManager("munge")
        self._slurmdbd_package = CharmedHPCPackageLifecycleManager("slurmdbd")

    def install(self) -> bool:
        """Install slurmdbd and munge to the system and setup paths."""
        if self._slurmdbd_package.install() is not True:
            return False
        systemd.service_stop("slurmdbd")

        if self._munge_package.install() is not True:
            return False
        systemd.service_stop("munge")

        # Create the state directory as it is not created as part of the package installation.
        STATE_DIR.mkdir()
        slurm_user_uid = getpwnam(SLURM_USER).pw_uid
        slurm_group_gid = getgrnam(SLURM_GROUP).gr_gid
        os.chown(f"{STATE_DIR}", slurm_user_uid, slurm_group_gid)

        return True

    def write_slurmdbd_conf(self, slurmdbd_parameters: dict) -> None:
        """Render slurmdbd.conf."""
        slurmdbd_conf = Path("/etc/slurm/slurmdbd.conf")
        slurm_user_uid = getpwnam(SLURM_USER).pw_uid
        slurm_group_gid = getgrnam(SLURM_GROUP).gr_gid

        header = textwrap.dedent(
            f"""
            #
            # {slurmdbd_conf} generated at {datetime.now()}
            #

            """
        )
        slurmdbd_conf.write_text(
            header + "\n".join([f"{k}={v}" for k, v in slurmdbd_parameters.items() if v != ""])
        )

        slurmdbd_conf.chmod(0o600)
        os.chown(f"{slurmdbd_conf}", slurm_user_uid, slurm_group_gid)

    def write_munge_key(self, munge_key_data: str) -> None:
        """Base64 decode and write the munge key."""
        munge_key_path = Path("/etc/munge/munge.key")
        munge_key_path.write_bytes(b64decode(munge_key_data.encode()))

    def write_jwt_rsa(self, jwt_rsa: str) -> None:
        """Write the jwt_rsa key and set permissions."""
        jwt_rsa_path = STATE_DIR / "jwt_hs256.key"
        slurm_user_uid = getpwnam(SLURM_USER).pw_uid
        slurm_group_gid = getgrnam(SLURM_GROUP).gr_gid

        jwt_rsa_path.write_text(jwt_rsa)
        jwt_rsa_path.chmod(0o600)

        os.chown(f"{jwt_rsa_path}", slurm_user_uid, slurm_group_gid)

    def stop_slurmdbd(self) -> None:
        """Stop slurmdbd."""
        systemd.service_stop("slurmdbd")

    def is_slurmdbd_active(self) -> bool:
        """Get if slurmdbd daemon is active or not."""
        return systemd.service_running("slurmdbd")

    def stop_munge(self) -> None:
        """Stop munge."""
        systemd.service_stop("munge")

    def start_munge(self) -> bool:
        """Start the munged process.

        Return True on success, and False otherwise.
        """
        logger.debug("Starting munge.")
        try:
            systemd.service_start("munge")
        # Ignore pyright error for is not a valid exception class, reportGeneralTypeIssues
        except SlurmdbdManagerError(
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

    def restart_slurmdbd(self) -> bool:
        """Restart the slurmdbd process.

        Return True on success, and False otherwise.
        """
        logger.debug("Attempting to restart slurmdbd.")
        try:
            systemd.service_restart("slurmdbd")
        # Ignore pyright error for is not a valid exception class, reportGeneralTypeIssues
        except SlurmdbdManagerError(
            "Cannot restart slurmdbd."
        ) as e:  # pyright: ignore [reportGeneralTypeIssues]
            logger.error(e)
            return False
        return True

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

    @property
    def hostname(self) -> str:
        """Return the hostname."""
        return socket.gethostname().split(".")[0]

    @property
    def version(self) -> str:
        """Return slurmdbd version."""
        return self._slurmdbd_package.version()
