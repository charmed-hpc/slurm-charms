# Copyright 2025 Canonical Ltd.
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

"""Classes and functions for composing Slurm service managers."""

__all__ = [
    "SecretManager",
    "PrometheusExporterManager",
    "SlurmManager",
]

import base64
import logging
import secrets
import shlex
import shutil
import socket
import textwrap
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from subprocess import CalledProcessError
from typing import Any, Protocol

import distro
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from hpc_libs.machine import (
    EnvManager,
    ServiceManager,
    SnapServiceManager,
    SystemctlServiceManager,
    apt,
    call,
    snap,
    systemctl,
)

from .errors import SlurmOpsError
from .options import marshal_options, parse_options

_logger = logging.getLogger(__name__)
UBUNTU_HPC_PPA_KEY = """
-----BEGIN PGP PUBLIC KEY BLOCK-----
Comment: Hostname:
Version: Hockeypuck 2.2

xsFNBGTuZb8BEACtJ1CnZe6/hv84DceHv+a54y3Pqq0gqED0xhTKnbj/E2ByJpmT
NlDNkpeITwPAAN1e3824Me76Qn31RkogTMoPJ2o2XfG253RXd67MPxYhfKTJcnM3
CEkmeI4u2Lynh3O6RQ08nAFS2AGTeFVFH2GPNWrfOsGZW03Jas85TZ0k7LXVHiBs
W6qonbsFJhshvwC3SryG4XYT+z/+35x5fus4rPtMrrEOD65hij7EtQNaE8owuAju
Kcd0m2b+crMXNcllWFWmYMV0VjksQvYD7jwGrWeKs+EeHgU8ZuqaIP4pYHvoQjag
umqnH9Qsaq5NAXiuAIAGDIIV4RdAfQIR4opGaVgIFJdvoSwYe3oh2JlrLPBlyxyY
dayDifd3X8jxq6/oAuyH1h5K/QLs46jLSR8fUbG98SCHlRmvozTuWGk+e07ALtGe
sGv78ToHKwoM2buXaTTHMwYwu7Rx8LZ4bZPHdersN1VW/m9yn1n5hMzwbFKy2s6/
D4Q2ZBsqlN+5aW2q0IUmO+m0GhcdaDv8U7RVto1cWWPr50HhiCi7Yvei1qZiD9jq
57oYZVqTUNCTPxi6NeTOdEc+YqNynWNArx4PHh38LT0bqKtlZCGHNfoAJLPVYhbB
b2AHj9edYtHU9AAFSIy+HstET6P0UDxy02IeyE2yxoUBqdlXyv6FL44E+wARAQAB
zRxMYXVuY2hwYWQgUFBBIGZvciBVYnVudHUgSFBDwsGOBBMBCgA4FiEErocSHcPk
oLD4H/Aj9tDF1ca+s3sFAmTuZb8CGwMFCwkIBwIGFQoJCAsCBBYCAwECHgECF4AA
CgkQ9tDF1ca+s3sz3w//RNawsgydrutcbKf0yphDhzWS53wgfrs2KF1KgB0u/H+u
6Kn2C6jrVM0vuY4NKpbEPCduOj21pTCepL6PoCLv++tICOLVok5wY7Zn3WQFq0js
Iy1wO5t3kA1cTD/05v/qQVBGZ2j4DsJo33iMcQS5AjHvSr0nu7XSvDDEE3cQE55D
87vL7lgGjuTOikPh5FpCoS1gpemBfwm2Lbm4P8vGOA4/witRjGgfC1fv1idUnZLM
TbGrDlhVie8pX2kgB6yTYbJ3P3kpC1ZPpXSRWO/cQ8xoYpLBTXOOtqwZZUnxyzHh
gM+hv42vPTOnCo+apD97/VArsp59pDqEVoAtMTk72fdBqR+BB77g2hBkKESgQIEq
EiE1/TOISioMkE0AuUdaJ2ebyQXugSHHuBaqbEC47v8t5DVN5Qr9OriuzCuSDNFn
6SBHpahN9ZNi9w0A/Yh1+lFfpkVw2t04Q2LNuupqOpW+h3/62AeUqjUIAIrmfeML
IDRE2VdquYdIXKuhNvfpJYGdyvx/wAbiAeBWg0uPSepwTfTG59VPQmj0FtalkMnN
ya2212K5q68O5eXOfCnGeMvqIXxqzpdukxSZnLkgk40uFJnJVESd/CxHquqHPUDE
fy6i2AnB3kUI27D4HY2YSlXLSRbjiSxTfVwNCzDsIh7Czefsm6ITK2+cVWs0hNQ=
=cs1s
-----END PGP PUBLIC KEY BLOCK-----
"""


class OpsManager(Protocol):  # pragma: no cover
    """Protocol for defining Slurm operation managers."""

    def service_manager_for(self, service: str) -> ServiceManager:  # noqa D102
        raise NotImplementedError

    def env_manager_for(self, service: str) -> EnvManager:  # noqa D102
        raise NotImplementedError

    def install(self) -> None:  # noqa D102
        raise NotImplementedError

    def version(self) -> str:  # noqa D102
        raise NotImplementedError

    def is_installed(self) -> bool:
        """Check if Slurm is installed."""
        try:
            self.version()
            return True
        except SlurmOpsError:
            return False

    @property
    def etc_path(self) -> Path:  # noqa D102
        raise NotImplementedError

    @property
    def var_lib_path(self) -> Path:  # noqa D102
        raise NotImplementedError


class SecretManager(Protocol):  # pragma: no cover
    """Protocol for defining Slurm secret managers."""

    def get(self) -> str:
        """Get the contents of the current secret file."""
        raise NotImplementedError

    def set(self, secret: str) -> None:
        """Set the contents of the secret file."""
        raise NotImplementedError

    def generate(self) -> None:
        """Generate a new, cryptographically secure secret."""
        raise NotImplementedError

    @property
    def path(self) -> Path:
        """Get path to the secret file."""
        raise NotImplementedError


class _AptManager(OpsManager):
    """Operations manager for the Slurm Debian package backend.

    Notes:
        This manager provides some environment variables that are automatically passed to the
        services with a systemctl override file. If you need to override the ExecStart parameter,
        ensure the new command correctly passes the environment variable to the command.
    """

    def __init__(self, service: str, /) -> None:
        self._service_name = service

    def service_manager_for(self, service: str) -> SystemctlServiceManager:
        """Return the `ServiceManager` for the specified `ServiceType`."""
        return SystemctlServiceManager(service)

    def env_manager_for(self, service: str) -> EnvManager:
        """Return the `_EnvManager` for the specified `ServiceType`."""
        return EnvManager(file=f"/etc/default/{service}")

    def install(self) -> None:
        """Install Slurm using the `slurm-wlm` Debian package set."""
        self._init_ubuntu_hpc_ppa()
        self._install_service()
        self._create_state_save_location()
        self._apply_overrides()

    def version(self) -> str:
        """Get the current version of Slurm installed on the system."""
        try:
            return apt.DebianPackage.from_installed_package(self._service_name).version.number
        except apt.PackageNotFoundError as e:
            raise SlurmOpsError(f"unable to retrieve {self._service_name} version. reason: {e}")

    @property
    def etc_path(self) -> Path:
        """Get the path to the Slurm configuration directory."""
        return Path("/etc/slurm")

    @property
    def var_lib_path(self) -> Path:
        """Get the path to the Slurm variable state data directory."""
        return Path("/var/lib/slurm")

    @staticmethod
    def _init_ubuntu_hpc_ppa() -> None:
        """Initialize `apt` to use Ubuntu HPC Debian package repositories.

        Raises:
            SlurmOpsError: Raised if `apt` fails to update with Ubuntu HPC repositories enabled.
        """
        _logger.debug("initializing apt to use ubuntu hpc debian package repositories")
        try:
            experimental = apt.DebianRepository(
                enabled=True,
                repotype="deb",
                uri="https://ppa.launchpadcontent.net/ubuntu-hpc/experimental/ubuntu",
                release=distro.codename(),
                groups=["main"],
            )
            experimental.import_key(UBUNTU_HPC_PPA_KEY)
            repositories = apt.RepositoryMapping()
            repositories.add(experimental)
            apt.update()
        except (apt.GPGKeyError, CalledProcessError) as e:
            raise SlurmOpsError(
                f"failed to initialize apt to use ubuntu hpc repositories. reason: {e}"
            )

    @staticmethod
    def _set_ulimit() -> None:
        """Set `ulimit` on nodes that need to be able to open many files at once."""
        ulimit_config_file = Path("/etc/security/limits.d/20-charmed-hpc-openfile.conf")
        ulimit_config = textwrap.dedent(
            """
            * soft nofile  1048576
            * hard nofile  1048576
            * soft memlock unlimited
            * hard memlock unlimited
            * soft stack unlimited
            * hard stack unlimited
            """
        )
        _logger.debug("setting ulimit configuration for node to:\n%s", ulimit_config)
        ulimit_config_file.write_text(ulimit_config)
        ulimit_config_file.chmod(0o644)

    def _install_service(self) -> None:
        """Install Slurm service and other necessary packages.

        Raises:
            SlurmOpsError: Raised if `apt` fails to install the required Slurm packages.
        """
        packages = [self._service_name]
        match self._service_name:
            case "sackd":
                packages.extend(["slurm-client"])
            case "slurmctld":
                packages.extend(["libpmix-dev", "mailutils", "prometheus-slurm-exporter"])
            case "slurmd":
                packages.extend(["slurm-client", "libpmix-dev", "openmpi-bin"])
            case "slurmrestd":
                packages.extend(["slurm-wlm-basic-plugins"])
            case _:
                _logger.debug(
                    "'%s' does not require any additional packages to be installed",
                    self._service_name,
                )

        _logger.debug("installing packages %s with apt", packages)
        try:
            apt.add_package(packages)
        except (apt.PackageNotFoundError, apt.PackageError) as e:
            raise SlurmOpsError(f"failed to install {self._service_name}. reason: {e}")

    def _create_state_save_location(self) -> None:
        """Create `StateSaveLocation` for Slurm services.

        Notes:
            `StateSaveLocation` is used by slurmctld, slurmd, and slurmdbd
            to checkpoint runtime information should a service crash, and it
            serves as the location where the JWT token used to generate user
            access tokens is stored as well.
        """
        _logger.debug("creating slurm `StateSaveLocation` directory")
        target = self.var_lib_path / "checkpoint"
        target.mkdir(mode=0o755, parents=True, exist_ok=True)
        self.var_lib_path.chmod(0o755)
        shutil.chown(self.var_lib_path, "slurm", "slurm")
        shutil.chown(target, "slurm", "slurm")

    def _apply_overrides(self) -> None:
        """Override defaults supplied provided by Slurm Debian packages."""
        match self._service_name:
            case "sackd":
                _logger.debug("overriding default sackd service configuration")
                sackd_restart_override = Path(
                    "/etc/systemd/system/sackd.service.d/10-charmed-hpc.conf"
                )
                sackd_restart_override.parent.mkdir(exist_ok=True, parents=True)
                sackd_restart_override.write_text(
                    textwrap.dedent(
                        """
                        [Unit]
                        StartLimitIntervalSec=90
                        StartLimitBurst=10
                        [Service]
                        Restart=on-failure
                        RestartSec=10
                        """
                    )
                )
                # TODO: https://github.com/charmed-hpc/hpc-libs/issues/54 -
                #   Make `sackd` create its service environment file so that we
                #   aren't required to manually create it here.
                _logger.debug("creating sackd environment file")
                self.env_manager_for("sackd").path.touch(mode=0o644, exist_ok=True)
            case "slurmctld":
                _logger.debug("overriding default slurmctld service configuration")
                self._set_ulimit()

                nofile_override = Path(
                    "/etc/systemd/system/slurmctld.service.d/10-charmed-hpc.conf"
                )
                nofile_override.parent.mkdir(exist_ok=True, parents=True)
                nofile_override.write_text(
                    textwrap.dedent(
                        """
                        [Service]
                        LimitMEMLOCK=infinity
                        LimitNOFILE=1048576
                        Restart=on-failure
                        RestartSec=10
                        """
                    )
                )
                systemctl("disable", "--now", "munge")
            case "slurmd":
                _logger.debug("overriding default slurmd service configuration")
                self._set_ulimit()

                nofile_override = Path("/etc/systemd/system/slurmd.service.d/10-charmed-hpc.conf")
                nofile_override.parent.mkdir(exist_ok=True, parents=True)
                nofile_override.write_text(
                    textwrap.dedent(
                        """
                        [Unit]
                        StartLimitIntervalSec=90
                        StartLimitBurst=10

                        [Service]
                        LimitMEMLOCK=infinity
                        LimitNOFILE=1048576
                        Restart=on-failure
                        RestartSec=10
                        """
                    )
                )

                systemctl("disable", "--now", "munge")
            case "slurmrestd":
                # TODO: https://github.com/charmed-hpc/hpc-libs/issues/39 -
                #   Make `slurmrestd` package preinst hook create the system user and group
                #   so that we do not need to do it manually here.
                _logger.debug("creating slurmrestd user and group")
                result = call("groupadd", "--gid", "64031", "slurmrestd", check=False)
                if result.returncode == 9:
                    _logger.debug("group 'slurmrestd' already exists")
                elif result.returncode != 0:
                    SlurmOpsError(f"failed to create group 'slurmrestd'. stderr: {result.stderr}")

                result = call(
                    "adduser",
                    "--system",
                    "--group",
                    "--uid",
                    "64031",
                    "--no-create-home",
                    "--home",
                    "/nonexistent",
                    "slurmrestd",
                    check=False,
                )
                if result.returncode == 9:
                    _logger.debug("user 'slurmrestd' already exists")
                elif result.returncode != 0:
                    raise SlurmOpsError(
                        f"failed to create user 'slurmrestd'. stderr: {result.stderr}"
                    )

                # slurmrestd's preinst script does not create environment file.
                _logger.debug("creating slurmrestd environment file")
                Path("/etc/default/slurmrestd").touch(mode=0o644)

                _logger.debug("overriding default slurmrestd service configuration")
                config_override = Path("/usr/lib/systemd/system/slurmrestd.service")
                config_override.write_text(
                    textwrap.dedent(
                        """
                        [Unit]
                        Description=Slurm REST daemon
                        After=network.target slurmctld.service
                        ConditionPathExists=/etc/slurm/slurm.conf
                        Documentation=man:slurmrestd(8)

                        [Service]
                        Type=simple
                        EnvironmentFile=-/etc/default/slurmrestd
                        Environment="SLURM_JWT=daemon"
                        ExecStart=/usr/sbin/slurmrestd $SLURMRESTD_OPTIONS -vv 0.0.0.0:6820
                        ExecReload=/bin/kill -HUP $MAINPID
                        User=slurmrestd
                        Group=slurmrestd

                        # Restart service if failed
                        Restart=on-failure
                        RestartSec=30s

                        [Install]
                        WantedBy=multi-user.target
                        """
                    )
                )
            case _:
                _logger.debug("'%s' does not require any overrides", self._service_name)

        systemctl("daemon-reload")


class _SnapManager(OpsManager):
    """Operations manager for the Slurm snap backend."""

    def service_manager_for(self, service: str) -> SnapServiceManager:
        """Return the `ServiceManager` for the specified `ServiceType`."""
        return SnapServiceManager(service, snap="slurm")

    def env_manager_for(self, service: str) -> EnvManager:
        """Return the `_EnvManager` for the specified `ServiceType`."""
        return EnvManager(file="/var/snap/slurm/common/.env")

    def install(self) -> None:
        """Install Slurm using the `slurm` snap."""
        snap("install", "slurm", "--channel", "23.11/stable", "--classic")
        self._create_state_save_location()
        self._apply_overrides()

    def is_installed(self) -> bool:
        """Check if the Slurm snap is installed."""
        try:
            self.version()
            return True
        except SlurmOpsError:
            return False

    def version(self) -> str:
        """Get the current version of the `slurm` snap installed on the system."""
        info = yaml.safe_load(snap("info", "slurm")[0])
        version = info.get("installed")
        if version is None:
            raise SlurmOpsError(
                "unable to retrieve snap info. ensure slurm is correctly installed"
            )

        return version.split(maxsplit=1)[0]

    @property
    def etc_path(self) -> Path:
        """Get the path to the Slurm configuration directory."""
        return Path("/var/snap/slurm/common/etc/slurm")

    @property
    def var_lib_path(self) -> Path:
        """Get the path to the Slurm variable state data directory."""
        return Path("/var/snap/slurm/common/var/lib/slurm")

    def _create_state_save_location(self) -> None:
        """Create `StateSaveLocation` for Slurm services.

        Notes:
            `StateSaveLocation` is used by slurmctld, slurmd, and slurmdbd
            to checkpoint runtime information should a service crash, and it
            serves as the location where the JWT token used to generate user
            access tokens is stored as well.
        """
        _logger.debug("creating slurm `StateSaveLocation` directory")
        target = self.var_lib_path / "checkpoint"
        target.mkdir(mode=0o755, parents=True, exist_ok=True)
        self.var_lib_path.chmod(0o755)
        shutil.chown(self.var_lib_path, "slurm", "slurm")
        shutil.chown(target, "slurm", "slurm")

    @staticmethod
    def _apply_overrides() -> None:
        """Override defaults provided by the Slurm snap."""
        snap("stop", "--disable", "slurm.munged")


# TODO: https://github.com/charmed-hpc/hpc-libs/issues/36 -
#   Use `jwtctl` to provide backend for generating, setting, and getting
#   jwt signing key used by `slurmctld` and `slurmdbd`. This way we also
#   won't need to pass the keyfile path to the `__init__` constructor.
#   .
#   Also, enable `jwtctl` to set the user and group for the keyfile.
class _JWTSecretManager(SecretManager):
    """Manage the `jwt_hs256.key` secret file."""

    def __init__(self, ops_manager: OpsManager, /, user: str, group: str) -> None:
        self._file = ops_manager.var_lib_path / "checkpoint" / "jwt_hs256.key"
        self._user = user
        self._group = group

    def get(self) -> str:
        """Get the contents of the current `jwt_hs256.key` secret file."""
        return self._file.read_text()

    def set(self, secret: str) -> None:
        """Set the contents of the `jwt_hs256.key` secret file."""
        self._file.write_text(secret)
        self._file.chmod(0o600)
        shutil.chown(self._file, self._user, self._group)

    def generate(self) -> None:
        """Generate a new, cryptographically secure `jwt_hs256.key` secret."""
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.set(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode()
        )

    @property
    def path(self) -> Path:
        """Get the path to the `jwt_hs256.key` secret file."""
        return self._file


class _SlurmSecretManager(SecretManager):
    """Manage the `slurm.key` secret file."""

    def __init__(self, ops_manager: OpsManager, /, user: str, group: str) -> None:
        self._file = ops_manager.etc_path / "slurm.key"
        self._user = user
        self._group = group

    def get(self) -> str:
        """Get the contents of the current `slurm.key` secret file."""
        return base64.b64encode(self._file.read_bytes()).decode()

    def set(self, secret: str) -> None:
        """Set the contents of the `slurm.key` secret file."""
        self._file.write_bytes(base64.b64decode(secret.encode()))
        self._file.chmod(0o600)
        shutil.chown(self._file, self._user, self._group)

    def generate(self) -> None:
        """Generate a new, cryptographically secure `slurm.key` secret."""
        key = secrets.token_bytes(2048)
        self.set(base64.b64encode(key).decode())

    @property
    def path(self) -> Path:
        """Get the path to the `slurm.key` secret file."""
        return self._file


class PrometheusExporterManager:
    """Manage `prometheus-slurm-exporter` service operations."""

    def __init__(self, ops_manager: OpsManager) -> None:
        self.service = ops_manager.service_manager_for("prometheus-slurm-exporter")
        self._env_manager = ops_manager.env_manager_for("prometheus-slurm-exporter")

    @property
    def args(self) -> list[str]:
        """Arguments passed to the `prometheus-slurm-exporter` executable."""
        args = self._env_manager.get("ARGS") or ""
        return shlex.split(args)

    @args.setter
    def args(self, args: Iterable[str]) -> None:
        self._env_manager.set({"ARGS": shlex.join(args)})

    @args.deleter
    def args(self) -> None:
        self._env_manager.unset("ARGS")


class SlurmManager(ABC):
    """Base class for composing Slurm service managers."""

    def __init__(self, service: str, snap: bool = False) -> None:
        self._service = service
        self._ops_manager = _SnapManager() if snap else _AptManager(service)
        self._env_manager = self._ops_manager.env_manager_for(service)

        self.service = self._ops_manager.service_manager_for(service)
        self.key = _SlurmSecretManager(self._ops_manager, user=self.user, group=self.group)
        self.jwt = _JWTSecretManager(self._ops_manager, user=self.user, group=self.group)
        self.exporter = PrometheusExporterManager(self._ops_manager)
        self.install = self._ops_manager.install
        self.is_installed = self._ops_manager.is_installed
        self.version = self._ops_manager.version

    @property
    def hostname(self) -> str:
        """Get the hostname of the machine the managed Slurm service is running on."""
        return socket.gethostname().split(".")[0]

    @property
    @abstractmethod
    def user(self) -> str:  # noqa D102  # pragma: no cover
        raise NotImplementedError

    @property
    @abstractmethod
    def group(self) -> str:  # noqa D102  # pragma: no cover
        raise NotImplementedError

    @contextmanager
    def _edit_options(self) -> Iterator[dict[str, Any]]:
        """Edit `<SERVICE>_OPTIONS` in the service environment file."""
        options = self._load_options()
        yield options
        self._save_options(options)

    def _load_options(self) -> dict[str, Any]:
        """Load `<SERVICE>_OPTIONS` from the service environment file."""
        return parse_options(self._env_manager.get(f"{self._service.upper()}_OPTIONS") or "")

    def _save_options(self, options: Mapping[str, Any]) -> None:
        """Save `<SERVICE>_OPTIONS` to the service environment file."""
        self._env_manager.set(
            {f"{self._service.upper()}_OPTIONS": marshal_options(options)}, quote=False
        )
