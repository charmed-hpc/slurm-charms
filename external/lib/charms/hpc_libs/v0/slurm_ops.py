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


"""Abstractions for managing Slurm operations via snap.

This library contains the `SlurmManagerBase` and `ServiceType` class
which provide high-level interfaces for managing Slurm within charmed operators.

### Example Usage

#### Managing a Slurm service

The `SlurmManagerBase` constructor receives a `ServiceType` enum. The enum instructs
the inheriting Slurm service manager how to manage its corresponding Slurm service on the host.

```python3
import charms.hpc_libs.v0.slurm_ops as slurm
from charms.hpc_libs.v0.slurm_ops import SlurmManagerBase, ServiceType

class SlurmctldManager(SlurmManagerBase):
    # Manage `slurmctld` service on host.

    def __init__(self) -> None:
        super().__init__(ServiceType.SLURMCTLD)


class ApplicationCharm(CharmBase):
    # Application charm that needs to use the Slurm snap.

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._slurm_manager = SlurmctldManager()
        self.framework.observe(
            self.on.install,
            self._on_install,
        )

    def _on_install(self, _) -> None:
        slurm.install()
        self.unit.set_workload_version(slurm.version())
        self._slurm_manager.config.set({"cluster-name": "cluster"})
```
"""

__all__ = [
    "format_key",
    "install",
    "version",
    "ConfigurationManager",
    "ServiceType",
    "SlurmManagerBase",
    "SlurmOpsError",
]

import json
import logging
import re
import socket
import subprocess
from collections.abc import Mapping
from enum import Enum
from typing import Any, Optional

import yaml

# The unique Charmhub library identifier, never change it
LIBID = "541fd767f90b40539cf7cd6e7db8fabf"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 5

# Charm library dependencies to fetch during `charmcraft pack`.
PYDEPS = ["pyyaml>=6.0.1"]

_logger = logging.getLogger(__name__)
_acronym = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_kebabize = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class SlurmOpsError(Exception):
    """Exception raised when a slurm operation failed."""

    @property
    def message(self) -> str:
        """Return message passed as argument to exception."""
        return self.args[0]


def format_key(key: str) -> str:
    """Format Slurm configuration keys from SlurmCASe into kebab case.

    Args:
        key: Slurm configuration key to convert to kebab case.

    Notes:
       Slurm configuration syntax does not follow proper PascalCasing
       format, so we cannot put keys directly through a kebab case converter
       to get the desired format. Some additional processing is needed for
       certain keys before the key can properly kebabized.

       For example, without additional preprocessing, the key `CPUs` will
       become `cp-us` if put through a kebabizer with being preformatted to `Cpus`.
    """
    if "CPUs" in key:
        key = key.replace("CPUs", "Cpus")
    key = _acronym.sub(r"-", key)
    return _kebabize.sub(r"-", key).lower()


def install() -> None:
    """Install Slurm."""
    # FIXME: Pin slurm to the stable channel
    _snap("install", "slurm", "--channel", "latest/candidate", "--classic")


def version() -> str:
    """Get the current version of Slurm installed on the system."""
    info = yaml.safe_load(_snap("info", "slurm"))
    if (ver := info.get("installed")) is None:
        raise SlurmOpsError("unable to retrive snap info. Ensure slurm is correctly installed")
    return ver.split(maxsplit=1)[0]


def _call(cmd: str, *args: str, stdin: Optional[str] = None) -> str:
    """Call a command with logging.

    Raises:
        SlurmOpsError: Raised if the command fails.
    """
    cmd = [cmd, *args]
    _logger.debug(f"Executing command {cmd}")
    try:
        return subprocess.check_output(cmd, input=stdin, stderr=subprocess.PIPE, text=True).strip()
    except subprocess.CalledProcessError as e:
        _logger.error(f"`{' '.join(cmd)}` failed")
        _logger.error(f"stderr: {e.stderr.decode()}")
        raise SlurmOpsError(f"command {cmd[0]} failed. Reason:\n{e.stderr.decode()}")


def _snap(*args) -> str:
    """Control snap by via executed `snap ...` commands.

    Raises:
        subprocess.CalledProcessError: Raised if snap command fails.
    """
    return _call("snap", *args)


def _mungectl(*args: str, stdin: Optional[str] = None) -> str:
    """Control munge via `slurm.mungectl ...`.

    Args:
        *args: Arguments to pass to `mungectl`.
        stdin: Input to pass to `mungectl` via stdin.

    Raises:
        subprocess.CalledProcessError: Raised if `mungectl` command fails.
    """
    return _call("slurm.mungectl", *args, stdin=stdin)


class ServiceType(Enum):
    """Type of Slurm service to manage."""

    MUNGED = "munged"
    PROMETHEUS_EXPORTER = "slurm-prometheus-exporter"
    SLURMD = "slurmd"
    SLURMCTLD = "slurmctld"
    SLURMDBD = "slurmdbd"
    SLURMRESTD = "slurmrestd"

    @property
    def config_name(self) -> str:
        """Configuration name on the slurm snap for this service type."""
        if self is ServiceType.SLURMCTLD:
            return "slurm"
        if self is ServiceType.MUNGED:
            return "munge"

        return self.value


class ServiceManager:
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
            raise SlurmOpsError("unable to retrive snap info. Ensure slurm is correctly installed")

        # Assume `services` contains the service, since `ServiceManager` is not exposed as a
        # public interface for now.
        # We don't do `"active" in state` because the word "active" is also part of "inactive" :)
        return "inactive" not in services[f"slurm.{self._service.value}"]


class ConfigurationManager:
    """Control configuration of a Slurm component."""

    def __init__(self, name: str) -> None:
        self._name = name

    def get_options(self, *keys: str) -> Mapping[str, Any]:
        """Get given configurations values for Slurm component."""
        configs = {}
        for key in keys:
            config = self.get(key)
            target = key.rsplit(".", maxsplit=1)[-1]
            configs[target] = config

        return configs

    def get(self, key: Optional[str] = None) -> Any:
        """Get specific configuration value for Slurm component."""
        key = f"{self._name}.{key}" if key else self._name
        config = json.loads(_snap("get", "-d", "slurm", key))
        return config[key]

    def set(self, config: Mapping[str, Any]) -> None:
        """Set configuration for Slurm component."""
        args = [f"{self._name}.{k}={json.dumps(v)}" for k, v in config.items()]
        _snap("set", "slurm", *args)

    def unset(self, *keys: str) -> None:
        """Unset configuration for Slurm component."""
        args = [f"{self._name}.{k}" for k in keys] if len(keys) > 0 else [self._name]
        _snap("unset", "slurm", *args)


class MungeManager(ServiceManager):
    """Manage `munged` service operations."""

    def __init__(self) -> None:
        service = ServiceType.MUNGED
        self._service = service
        self.config = ConfigurationManager(service.config_name)

    def get_key(self) -> str:
        """Get the current munge key.

        Returns:
            The current munge key as a base64-encoded string.
        """
        return _mungectl("key", "get")

    def set_key(self, key: str) -> None:
        """Set a new munge key.

        Args:
            key: A new, base64-encoded munge key.
        """
        _mungectl("key", "set", stdin=key)

    def generate_key(self) -> None:
        """Generate a new, cryptographically secure munge key."""
        _mungectl("key", "generate")


class PrometheusExporterManager(ServiceManager):
    """Manage `slurm-prometheus-exporter` service operations."""

    def __init__(self) -> None:
        self._service = ServiceType.PROMETHEUS_EXPORTER


class SlurmManagerBase(ServiceManager):
    """Base manager for Slurm services."""

    def __init__(self, service: ServiceType) -> None:
        self._service = service
        self.config = ConfigurationManager(service.config_name)
        self.munge = MungeManager()
        self.exporter = PrometheusExporterManager()

    @property
    def hostname(self) -> str:
        """The hostname where this manager is running."""
        return socket.gethostname().split(".")[0]
