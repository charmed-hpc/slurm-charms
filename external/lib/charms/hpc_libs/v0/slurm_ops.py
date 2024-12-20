# Copyright 2024 Canonical Ltd.
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

"""Abstractions for managing Slurm operations via snap or systemd.

This library contains manager classes that provide high-level interfaces
for managing Slurm operations within charmed operators.

### Note

This charm library depends on the `charms.operator_libs_linux.v0.apt` charm library, which can
be imported by running `charmcraft fetch-lib charms.operator_libs_linux.v0.apt`.

### Example Usage

#### Managing the `slurmctld` service

The `SlurmctldManager` class manages the operations of the Slurm controller service.
You can pass the boolean keyword argument `snap=True` or `snap=False` to instruct
`SlurmctldManager` to either use the Slurm snap package or Debian package respectively.

```python3
from charms.hpc_libs.v0.slurm_ops import SlurmctldManager


class ApplicationCharm(CharmBase):
    # Application charm that needs to use the Slurm snap.

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._slurmctld = SlurmctldManager(snap=True)
        self.framework.observe(self.on.install, self._on_install)

    def _on_install(self, _) -> None:
        self._slurmctld.install()
        self.unit.set_workload_version(self._slurmctld.version())
        with self._slurmctld.config.edit() as config:
            config.cluster_name = "cluster"
```
"""

__all__ = [
    "SackdManager",
    "SlurmOpsError",
    "SlurmctldManager",
    "SlurmdManager",
    "SlurmdbdManager",
    "SlurmrestdManager",
]

import logging
import os
import shutil
import socket
import subprocess
import textwrap
from abc import ABC, abstractmethod
from collections.abc import Mapping
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union

import distro
import dotenv
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from slurmutils.editors import (
    acctgatherconfig,
    cgroupconfig,
    gresconfig,
    slurmconfig,
    slurmdbdconfig,
)
from slurmutils.models import (
    AcctGatherConfig,
    CgroupConfig,
    GRESConfig,
    SlurmConfig,
    SlurmdbdConfig,
)

try:
    import charms.operator_libs_linux.v0.apt as apt
except ImportError as e:
    raise ImportError(
        "`slurm_ops` requires the `charms.operator_libs_linux.v0.apt` charm library to work",
        name=e.name,
        path=e.path,
    )

# The unique Charmhub library identifier, never change it
LIBID = "541fd767f90b40539cf7cd6e7db8fabf"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 11

# Charm library dependencies to fetch during `charmcraft pack`.
PYDEPS = [
    "cryptography~=44.0.0",
    "pyyaml>=6.0.2",
    "python-dotenv~=1.0.1",
    "slurmutils~=0.11.0",
    "distro~=1.9.0",
]

_logger = logging.getLogger(__name__)


class SlurmOpsError(Exception):
    """Exception raised when a slurm operation failed."""

    @property
    def message(self) -> str:
        """Return message passed as argument to exception."""
        return self.args[0]


def _call(
    cmd: str, *args: str, stdin: Optional[str] = None, check: bool = True
) -> subprocess.CompletedProcess:
    """Call a command with logging.

    If the `check` argument is set to `False`, the command call
    will not raise an error if the command fails.

    Raises:
        SlurmOpsError: Raised if the executed command fails.
    """
    cmd = [cmd, *args]
    _logger.debug(f"executing command {cmd}")

    result = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if result.returncode != 0:
        _logger.error(f"command {cmd} failed with message {result.stderr}")
        if check:
            raise SlurmOpsError(f"command {cmd} failed. stderr:\n{result.stderr}")

    return subprocess.CompletedProcess(
        args=result.args,
        stdout=result.stdout.strip() if result.stdout else None,
        stderr=result.stderr.strip() if result.stderr else None,
        returncode=result.returncode,
    )


def _snap(*args) -> str:
    """Control snap by via executed `snap ...` commands.

    Raises:
        SlurmOpsError: Raised if snap command fails.
    """
    return _call("snap", *args).stdout


def _systemctl(*args) -> str:
    """Control systemd units via `systemctl ...` commands.

    Raises:
        SlurmOpsError: Raised if systemctl command fails.
    """
    return _call("systemctl", *args).stdout


def _mungectl(*args, stdin: Optional[str] = None) -> str:
    """Control munge via `mungectl ...` commands.

    Raises:
        SlurmOpsError: Raised if mungectl command fails.
    """
    return _call("mungectl", *args, stdin=stdin).stdout


class _ServiceType(Enum):
    """Type of Slurm service to manage."""

    MUNGE = "munge"
    PROMETHEUS_EXPORTER = "prometheus-slurm-exporter"
    SACKD = "sackd"
    SLURMD = "slurmd"
    SLURMCTLD = "slurmctld"
    SLURMDBD = "slurmdbd"
    SLURMRESTD = "slurmrestd"

    @property
    def config_name(self) -> str:
        """Configuration name on the slurm snap for this service type."""
        if self is _ServiceType.SLURMCTLD:
            return "slurm"

        return self.value


class _EnvManager:
    """Control configuration of environment variables used in Slurm components.

    Every configuration value is automatically uppercased.
    """

    def __init__(self, file: Union[str, os.PathLike]) -> None:
        self._file: Path = Path(file)

    def get(self, key: str) -> Optional[str]:
        """Get specific environment variable for service."""
        return dotenv.get_key(self._file, key.upper())

    def set(self, config: Mapping[str, Any]) -> None:
        """Set environment variable for service."""
        for key, value in config.items():
            dotenv.set_key(self._file, key.upper(), str(value))

    def unset(self, key: str) -> None:
        """Unset environment variable for service."""
        dotenv.unset_key(self._file, key.upper())


class _ConfigManager(ABC):
    """Control a Slurm configuration file."""

    def __init__(self, config_path: Union[str, Path], user: str, group: str) -> None:
        self._config_path = config_path
        self._user = user
        self._group = group

    @abstractmethod
    def load(self):
        """Load the current configuration from the configuration file."""

    @abstractmethod
    def dump(self, config) -> None:
        """Dump new configuration into configuration file.

        Notes:
            Overwrites current configuration file. If just updating the
            current configuration, use `edit` instead.
        """

    @contextmanager
    @abstractmethod
    def edit(self):
        """Edit the current configuration file."""


class _AcctGatherConfigManager(_ConfigManager):
    """Manage the `acct_gather.conf` configuration file."""

    def load(self) -> AcctGatherConfig:
        """Load the current `acct_gather.conf` configuration file."""
        return acctgatherconfig.load(self._config_path)

    def dump(self, config: AcctGatherConfig) -> None:
        """Dump new configuration into `acct_gather.conf` configuration file."""
        acctgatherconfig.dump(
            config, self._config_path, mode=0o600, user=self._user, group=self._group
        )

    @contextmanager
    def edit(self) -> AcctGatherConfig:
        """Edit the current `acct_gather.conf` configuration file."""
        with acctgatherconfig.edit(
            self._config_path, mode=0o600, user=self._user, group=self._group
        ) as config:
            yield config


class _CgroupConfigManager(_ConfigManager):
    """Control the `cgroup.conf` configuration file."""

    def load(self) -> CgroupConfig:
        """Load the current `cgroup.conf` configuration file."""
        return cgroupconfig.load(self._config_path)

    def dump(self, config: CgroupConfig) -> None:
        """Dump new configuration into `cgroup.conf` configuration file."""
        cgroupconfig.dump(
            config, self._config_path, mode=0o644, user=self._user, group=self._group
        )

    @contextmanager
    def edit(self) -> CgroupConfig:
        """Edit the current `cgroup.conf` configuration file."""
        with cgroupconfig.edit(
            self._config_path, mode=0o644, user=self._user, group=self._group
        ) as config:
            yield config


class _GRESConfigManager(_ConfigManager):
    """Manage the `gres.conf` configuration file."""

    def load(self) -> GRESConfig:
        """Load the current `gres.conf` configuration files."""
        return gresconfig.load(self._config_path)

    def dump(self, config: GRESConfig) -> None:
        """Dump new configuration into `gres.conf` configuration file."""
        gresconfig.dump(config, self._config_path, mode=0o644, user=self._user, group=self._group)

    @contextmanager
    def edit(self) -> GRESConfig:
        """Edit the current `gres.conf` configuration file."""
        with gresconfig.edit(
            self._config_path, mode=0o644, user=self._user, group=self._group
        ) as config:
            yield config


class _SlurmConfigManager(_ConfigManager):
    """Control the `slurm.conf` configuration file."""

    def load(self) -> SlurmConfig:
        """Load the current `slurm.conf` configuration file."""
        return slurmconfig.load(self._config_path)

    def dump(self, config: SlurmConfig) -> None:
        """Dump new configuration into `slurm.conf` configuration file."""
        slurmconfig.dump(config, self._config_path, mode=0o644, user=self._user, group=self._group)

    @contextmanager
    def edit(self) -> SlurmConfig:
        """Edit the current `slurm.conf` configuration file."""
        with slurmconfig.edit(
            self._config_path, mode=0o644, user=self._user, group=self._group
        ) as config:
            yield config


class _SlurmdbdConfigManager(_ConfigManager):
    """Control the `slurmdbd.conf` configuration file."""

    def load(self) -> SlurmdbdConfig:
        """Load the current `slurmdbd.conf` configuration file."""
        return slurmdbdconfig.load(self._config_path)

    def dump(self, config: SlurmdbdConfig) -> None:
        """Dump new configuration into `slurmdbd.conf` configuration file."""
        slurmdbdconfig.dump(
            config, self._config_path, mode=0o600, user=self._user, group=self._group
        )

    @contextmanager
    def edit(self) -> SlurmdbdConfig:
        """Edit the current `slurmdbd.conf` configuration file."""
        with slurmdbdconfig.edit(
            self._config_path, mode=0o600, user=self._user, group=self._group
        ) as config:
            yield config


class _ServiceManager(ABC):
    """Control a Slurm service."""

    def __init__(self, service: _ServiceType) -> None:
        self._service = service

    @abstractmethod
    def enable(self) -> None:
        """Enable service."""

    @abstractmethod
    def disable(self) -> None:
        """Disable service."""

    @abstractmethod
    def restart(self) -> None:
        """Restart service."""

    @abstractmethod
    def active(self) -> bool:
        """Return True if the service is active."""

    @property
    def type(self) -> _ServiceType:
        """Return the service type of the managed service."""
        return self._service


class _SystemctlServiceManager(_ServiceManager):
    """Control a Slurm service using systemctl services."""

    def enable(self) -> None:
        """Enable service.

        Raises:
            SlurmOpsError: Raised if `systemctl enable ...` returns a non-zero returncode.
        """
        _systemctl("enable", "--now", self._service.value)

    def disable(self) -> None:
        """Disable service."""
        _systemctl("disable", "--now", self._service.value)

    def restart(self) -> None:
        """Restart service."""
        _systemctl("reload-or-restart", self._service.value)

    def active(self) -> bool:
        """Return True if the service is active."""
        return (
            _call("systemctl", "is-active", "--quiet", self._service.value, check=False).returncode
            == 0
        )


class _SnapServiceManager(_ServiceManager):
    """Control a Slurm service."""

    def enable(self) -> None:
        """Enable service."""
        _snap("start", "--enable", f"slurm.{self._service.value}")

    def disable(self) -> None:
        """Disable service."""
        _snap("stop", "--disable", f"slurm.{self._service.value}")

    def restart(self) -> None:
        """Restart service."""
        _snap("restart", f"slurm.{self._service.value}")

    def active(self) -> bool:
        """Return True if the service is active."""
        info = yaml.safe_load(_snap("info", "slurm"))
        if (services := info.get("services")) is None:
            raise SlurmOpsError("unable to retrive snap info. ensure slurm is correctly installed")

        # Assume `services` contains the service, since `ServiceManager` is not exposed as a
        # public interface for now.
        # We don't do `"active" in state` because the word "active" is also part of "inactive" :)
        return "inactive" not in services[f"slurm.{self._service.value}"]


class _OpsManager(ABC):
    """Manager to control the lifecycle of Slurm-related services."""

    @abstractmethod
    def install(self) -> None:
        """Install Slurm."""

    @abstractmethod
    def version(self) -> str:
        """Get the current version of Slurm installed on the system."""

    @property
    @abstractmethod
    def etc_path(self) -> Path:
        """Get the path to the Slurm configuration directory."""

    @property
    @abstractmethod
    def var_lib_path(self) -> Path:
        """Get the path to the Slurm variable state data directory."""

    @abstractmethod
    def service_manager_for(self, service: _ServiceType) -> _ServiceManager:
        """Return the `ServiceManager` for the specified `ServiceType`."""

    @abstractmethod
    def env_manager_for(self, service: _ServiceType) -> _EnvManager:
        """Return the `_EnvManager` for the specified `ServiceType`."""


class _SnapManager(_OpsManager):
    """Operations manager for the Slurm snap backend."""

    def install(self) -> None:
        """Install Slurm using the `slurm` snap."""
        # TODO: https://github.com/charmed-hpc/hpc-libs/issues/35 -
        #   Pin Slurm snap to stable channel.
        _snap("install", "slurm", "--channel", "latest/candidate", "--classic")
        # TODO: https://github.com/charmed-hpc/slurm-snap/issues/49 -
        #   Request automatic alias for the Slurm snap so we don't need to do it here.
        #   We will possibly need to account for a third-party Slurm snap installation
        #   where aliasing is not automatically performed.
        _snap("alias", "slurm.mungectl", "mungectl")

    def version(self) -> str:
        """Get the current version of the `slurm` snap installed on the system."""
        info = yaml.safe_load(_snap("info", "slurm"))
        if (ver := info.get("installed")) is None:
            raise SlurmOpsError(
                "unable to retrieve snap info. ensure slurm is correctly installed"
            )
        return ver.split(maxsplit=1)[0]

    @property
    def etc_path(self) -> Path:
        """Get the path to the Slurm configuration directory."""
        return Path("/var/snap/slurm/common/etc/slurm")

    @property
    def var_lib_path(self) -> Path:
        """Get the path to the Slurm variable state data directory."""
        return Path("/var/snap/slurm/common/var/lib/slurm")

    def service_manager_for(self, service: _ServiceType) -> _ServiceManager:
        """Return the `ServiceManager` for the specified `ServiceType`."""
        return _SnapServiceManager(service)

    def env_manager_for(self, service: _ServiceType) -> _EnvManager:
        """Return the `_EnvManager` for the specified `ServiceType`."""
        return _EnvManager(file="/var/snap/slurm/common/.env")


class _AptManager(_OpsManager):
    """Operations manager for the Slurm Debian package backend.

    Notes:
        This manager provides some environment variables that are automatically passed to the
        services with a systemctl override file. If you need to override the ExecStart parameter,
        ensure the new command correctly passes the environment variable to the command.
    """

    def __init__(self, service: _ServiceType) -> None:
        self._service_name = service.value
        self._env_file = Path(f"/etc/default/{self._service_name}")

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

    def service_manager_for(self, service: _ServiceType) -> _ServiceManager:
        """Return the `ServiceManager` for the specified `ServiceType`."""
        return _SystemctlServiceManager(service)

    def env_manager_for(self, service: _ServiceType) -> _EnvManager:
        """Return the `_EnvManager` for the specified `ServiceType`."""
        return _EnvManager(file=f"/etc/default/{service.value}")

    @staticmethod
    def _init_ubuntu_hpc_ppa() -> None:
        """Initialize `apt` to use Ubuntu HPC Debian package repositories.

        Raises:
            SlurmOpsError: Raised if `apt` fails to update with Ubuntu HPC repositories enabled.
        """
        _logger.debug("initializing apt to use ubuntu hpc debian package repositories")
        experimental = apt.DebianRepository(
            enabled=True,
            repotype="deb",
            uri="https://ppa.launchpadcontent.net/ubuntu-hpc/experimental/ubuntu",
            release=distro.codename(),
            groups=["main"],
        )
        experimental.import_key(
            textwrap.dedent(
                """
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
            )
        )
        repositories = apt.RepositoryMapping()
        repositories.add(experimental)

        try:
            apt.update()
        except subprocess.CalledProcessError as e:
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
        packages = [self._service_name, "munge", "mungectl"]
        match self._service_name:
            case "sackd":
                packages.extend(["slurm-client"])
            case "slurmctld":
                packages.extend(["libpmix-dev", "mailutils", "prometheus-slurm-exporter"])
            case "slurmd":
                packages.extend(["libpmix-dev", "openmpi-bin"])
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
                config_override = Path(
                    "/etc/systemd/system/sackd.service.d/10-sackd-config-server.conf"
                )
                config_override.parent.mkdir(parents=True, exist_ok=True)
                config_override.write_text(
                    textwrap.dedent(
                        """
                        [Service]
                        ExecStart=
                        ExecStart=/usr/sbin/sackd --systemd --conf-server $SACKD_CONFIG_SERVER
                        """
                    )
                )

                # TODO: https://github.com/charmed-hpc/hpc-libs/issues/54 -
                #   Make `sackd` create its service environment file so that we
                #   aren't required to manually create it here.
                _logger.debug("creating sackd environment file")
                self._env_file.touch(mode=0o644, exist_ok=True)
            case "slurmctld":
                _logger.debug("overriding default slurmctld service configuration")
                self._set_ulimit()

                nofile_override = Path(
                    "/etc/systemd/system/slurmctld.service.d/10-slurmctld-nofile.conf"
                )
                nofile_override.parent.mkdir(exist_ok=True, parents=True)
                nofile_override.write_text(
                    textwrap.dedent(
                        """
                        [Service]
                        LimitMEMLOCK=infinity
                        LimitNOFILE=1048576
                        """
                    )
                )
            case "slurmd":
                _logger.debug("overriding default slurmd service configuration")
                self._set_ulimit()

                nofile_override = Path(
                    "/etc/systemd/system/slurmctld.service.d/10-slurmd-nofile.conf"
                )
                nofile_override.parent.mkdir(exist_ok=True, parents=True)
                nofile_override.write_text(
                    textwrap.dedent(
                        """
                        [Service]
                        LimitMEMLOCK=infinity
                        LimitNOFILE=1048576
                        """
                    )
                )

                config_override = Path(
                    "/etc/systemd/system/slurmd.service.d/20-slurmd-config-server.conf"
                )
                config_override.parent.mkdir(exist_ok=True, parents=True)
                config_override.write_text(
                    textwrap.dedent(
                        """
                        [Service]
                        ExecStart=
                        ExecStart=/usr/bin/sh -c "/usr/sbin/slurmd -D -s $${SLURMD_CONFIG_SERVER:+--conf-server $$SLURMD_CONFIG_SERVER} $$SLURMD_OPTIONS"
                        """
                    )
                )
            case "slurmrestd":
                # TODO: https://github.com/charmed-hpc/hpc-libs/issues/39 -
                #   Make `slurmrestd` package preinst hook create the system user and group
                #   so that we do not need to do it manually here.
                _logger.debug("creating slurmrestd user and group")
                result = _call("groupadd", "--gid", "64031", "slurmrestd", check=False)
                if result.returncode == 9:
                    _logger.debug("group 'slurmrestd' already exists")
                elif result.returncode != 0:
                    SlurmOpsError(f"failed to create group 'slurmrestd'. stderr: {result.stderr}")

                result = _call(
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
                        After=network.target munge.service slurmctld.service
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

        _systemctl("daemon-reload")


# TODO: https://github.com/charmed-hpc/hpc-libs/issues/36 -
#   Use `jwtctl` to provide backend for generating, setting, and getting
#   jwt signing key used by `slurmctld` and `slurmdbd`. This way we also
#   won't need to pass the keyfile path to the `__init__` constructor.
#   .
#   Also, enable `jwtctl` to set the user and group for the keyfile.
class _JWTKeyManager:
    """Control the jwt signing key used by Slurm."""

    def __init__(self, ops_manager: _OpsManager, user: str, group: str) -> None:
        self._keyfile = ops_manager.var_lib_path / "checkpoint/jwt_hs256.key"
        self._user = user
        self._group = group

    def get(self) -> str:
        """Get the current jwt key."""
        return self._keyfile.read_text()

    def set(self, key: str) -> None:
        """Set a new jwt key."""
        self._keyfile.write_text(key)
        self._keyfile.chmod(0o600)
        shutil.chown(self._keyfile, self._user, self._group)

    def generate(self) -> None:
        """Generate a new, cryptographically secure jwt key."""
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.set(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode()
        )


# TODO: https://github.com/charmed-hpc/mungectl/issues/5 -
#   Have `mungectl` set user and group permissions on the munge.key file.
class _MungeKeyManager:
    """Control the munge key via `mungectl ...` commands."""

    @staticmethod
    def get() -> str:
        """Get the current munge key.

        Returns:
            The current munge key as a base64-encoded string.
        """
        return _mungectl("key", "get")

    @staticmethod
    def set(key: str) -> None:
        """Set a new munge key.

        Args:
            key: A new, base64-encoded munge key.
        """
        _mungectl("key", "set", stdin=key)

    @staticmethod
    def generate() -> None:
        """Generate a new, cryptographically secure munge key."""
        _mungectl("key", "generate")


class _MungeManager:
    """Manage `munged` service operations."""

    def __init__(self, ops_manager: _OpsManager) -> None:
        self.service = ops_manager.service_manager_for(_ServiceType.MUNGE)
        self.key = _MungeKeyManager()


class _PrometheusExporterManager:
    """Manage `prometheus-slurm-exporter` service operations."""

    def __init__(self, ops_manager: _OpsManager) -> None:
        self.service = ops_manager.service_manager_for(_ServiceType.PROMETHEUS_EXPORTER)


class _SlurmManagerBase:
    """Base manager for Slurm services."""

    def __init__(self, service: _ServiceType, snap: bool = False) -> None:
        self._ops_manager = _SnapManager() if snap else _AptManager(service)
        self.service = self._ops_manager.service_manager_for(service)
        self.munge = _MungeManager(self._ops_manager)
        self.jwt = _JWTKeyManager(self._ops_manager, self.user, self.group)
        self.exporter = _PrometheusExporterManager(self._ops_manager)
        self.install = self._ops_manager.install
        self.version = self._ops_manager.version

    @property
    def user(self) -> str:
        """Get the user that managed service is running as."""
        return "slurm"

    @property
    def group(self) -> str:
        """Get the group that the managed service is running as."""
        return "slurm"

    @property
    def hostname(self) -> str:
        """The hostname where this manager is running."""
        return socket.gethostname().split(".")[0]

    @staticmethod
    def scontrol(*args) -> str:
        """Control Slurm via `scontrol` commands.

        Raises:
            SlurmOpsError: Raised if `scontrol` command fails.
        """
        return _call("scontrol", *args).stdout


class SackdManager(_SlurmManagerBase):
    """Manager for the `sackd` service."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(service=_ServiceType.SACKD, *args, **kwargs)
        self._env_manager = self._ops_manager.env_manager_for(_ServiceType.SACKD)

    @property
    def config_server(self) -> str | None:
        """Get the configuration server address of this `sackd` node."""
        return self._env_manager.get("SACKD_CONFIG_SERVER")

    @config_server.setter
    def config_server(self, addr: str) -> None:
        """Set the configuration server address of this `sackd` node.

        Sets the `--conf-server` option for `sackd`.
        """
        self._env_manager.set({"SACKD_CONFIG_SERVER": addr})

    @config_server.deleter
    def config_server(self) -> None:
        """Unset the configuration server address of this `sackd` node."""
        self._env_manager.unset("SACKD_CONFIG_SERVER")


class SlurmctldManager(_SlurmManagerBase):
    """Manager for the `slurmctld` service."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(service=_ServiceType.SLURMCTLD, *args, **kwargs)
        self.config = _SlurmConfigManager(
            self._ops_manager.etc_path / "slurm.conf", self.user, self.group
        )
        self.acct_gather = _AcctGatherConfigManager(
            self._ops_manager.etc_path / "acct_gather.conf", self.user, self.group
        )
        self.cgroup = _CgroupConfigManager(
            self._ops_manager.etc_path / "cgroup.conf", self.user, self.group
        )
        self.gres = _GRESConfigManager(
            self._ops_manager.etc_path / "gres.conf", self.user, self.group
        )


class SlurmdManager(_SlurmManagerBase):
    """Manager for the `slurmd` service."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(service=_ServiceType.SLURMD, *args, **kwargs)
        self._env_manager = self._ops_manager.env_manager_for(_ServiceType.SLURMD)

    @property
    def user(self) -> str:
        """Get the `SlurmdUser`."""
        return "root"

    @property
    def group(self) -> str:
        """Get the `SlurmdUser` group."""
        return "root"

    @property
    def config_server(self) -> str | None:
        """Get the configuration server address of this `slurmd` node."""
        return self._env_manager.get("SLURMD_CONFIG_SERVER")

    @config_server.setter
    def config_server(self, addr: str) -> None:
        """Set the configuration server address of this `slurmd` node.

        Sets the `--conf-server` option for `slurmd`.
        """
        self._env_manager.set({"SLURMD_CONFIG_SERVER": addr})

    @config_server.deleter
    def config_server(self) -> None:
        """Unset the configuration server address of this `slurmd` node."""
        self._env_manager.unset("SLURMD_CONFIG_SERVER")


class SlurmdbdManager(_SlurmManagerBase):
    """Manager for the `slurmdbd` service."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(service=_ServiceType.SLURMDBD, *args, **kwargs)
        self._env_manager = self._ops_manager.env_manager_for(_ServiceType.SLURMDBD)
        self.config = _SlurmdbdConfigManager(
            self._ops_manager.etc_path / "slurmdbd.conf", self.user, self.group
        )

    @property
    def mysql_unix_port(self) -> str | None:
        """Get the URI of the unix socket `slurmdbd` uses to communicate with MySQL."""
        return self._env_manager.get("MYSQL_UNIX_PORT")

    @mysql_unix_port.setter
    def mysql_unix_port(self, socket_path: Union[str, os.PathLike]) -> None:
        """Set the unix socket URI that `slurmdbd` will use to communicate with MySQL."""
        self._env_manager.set({"MYSQL_UNIX_PORT": socket_path})

    @mysql_unix_port.deleter
    def mysql_unix_port(self) -> None:
        """Delete the configured unix socket URI."""
        self._env_manager.unset("MYSQL_UNIX_PORT")


class SlurmrestdManager(_SlurmManagerBase):
    """Manager for the `slurmrestd` service."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(service=_ServiceType.SLURMRESTD, *args, **kwargs)
        self.config = _SlurmConfigManager(
            self._ops_manager.etc_path / "slurm.conf", user=self.user, group=self.group
        )

    @property
    def user(self) -> str:
        """Get the user that the `slurmrestd` service will run as."""
        return "slurmrestd"

    @property
    def group(self):
        """Get the group that the `slurmrestd` service will run as."""
        return "slurmrestd"
