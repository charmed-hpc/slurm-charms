# Copyright 2026 Canonical Ltd.
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

"""Slurmctld email notification features."""

import configparser
import logging
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from charmed_hpc_libs.errors import Error
from charmlibs import apt
from constants import DEFAULT_SLURM_MAIL_CONFIG, SLURM_MAIL_CONFIG_PATH
from pydantic import BaseModel, ConfigDict, Field

_logger = logging.getLogger(__name__)


class MailOpsError(Error):
    """Exception raised when mail service operations fail."""


class MailConfig(BaseModel):
    """Mail configuration.

    Attributes:
        server: Hostname or IP address of the SMTP server.
        port: Port number for the SMTP server.
        use_tls: "yes" to enable or "no" to disable transport layer security (TLS).
        user: Username for SMTP authentication.
        password: Password for SMTP authentication.
        from_name: Name to appear in the signature of sent emails.
    """

    model_config = ConfigDict(validate_assignment=True)

    server: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    use_tls: Literal["yes", "no"] | None = None
    user: str | None = None
    password: str | None = Field(default=None, repr=False)
    from_name: str | None = None


@contextmanager
def configure() -> Generator[MailConfig]:
    """Configure mail settings via a context manager.

    Use as:
        with configure() as config:
            config.server = "smtp.example.com"
            config.port = 587
            config.use_tls = "yes"
            config.user = "user"
            config.password = "secret"
            config.from_name = "The Charmed HPC Cluster Team"

    See the MailConfig class for available configuration options.

    Args:
        config_path: Configuration file path. Defaults to SLURM_MAIL_CONFIG_PATH.

    Yields:
        MailConfig instance to be updated within the context.

    Raises:
        MailOpsError: If an error occurs during configuration.
    """
    config_model = MailConfig()
    yield config_model

    # Match model fields to slurm-mail.conf keys
    config_options = {
        "smtpServer": config_model.server,
        "smtpPort": str(config_model.port) if config_model.port else None,
        "smtpUseTls": config_model.use_tls,
        "smtpUserName": config_model.user,
        "smtpPassword": config_model.password,
        "emailFromName": config_model.from_name,
    }

    config_path = Path(SLURM_MAIL_CONFIG_PATH)
    if not config_path.exists():
        _initialize_config_file(config_path)

    config = configparser.RawConfigParser()
    # Preserve camelCase keys, such as smtpServer
    config.optionxform = str  # pyright: ignore[reportAttributeAccessIssue]
    config.read(config_path)

    # Ensure the required section exists, reinitialize if not
    section = "slurm-send-mail"
    if not config.has_section(section):
        _logger.warning(
            "configuration file damaged: missing required section '%s'. reinitializing", section
        )
        _initialize_config_file(config_path)
        config.read(config_path)

    # Determine configuration changes
    config_changed = False
    for config_key, new_value in config_options.items():
        if new_value is None:
            continue

        # Fall back to the value `None` if the key does not exist
        if config.get(section, config_key, fallback=None) != new_value:
            config.set(section, config_key, new_value)
            config_changed = True

    if not config_changed:
        _logger.info("no changes required to slurm-mail configuration")
        return
    _write_config_file(config_path, config)


def install() -> None:
    """Ensure slurm-mail package is installed.

    Raises:
        MailOpsError: If an error occurs during package installation.
    """
    try:
        apt.add_package("slurm-mail")
    except (apt.PackageNotFoundError, apt.PackageError) as e:
        raise MailOpsError(f"Failed to install slurm-mail package. Reason: {e}") from e

    _initialize_config_file()


def uninstall() -> None:
    """Ensure slurm-mail package is uninstalled.

    Raises:
        MailOpsError: If an error occurs during package removal.
    """
    try:
        apt.remove_package("slurm-mail")
    except (apt.PackageNotFoundError, apt.PackageError) as e:
        raise MailOpsError(f"Failed to uninstall slurm-mail package. Reason: {e}") from e


def _initialize_config_file(
    config_path: Path = Path(SLURM_MAIL_CONFIG_PATH),
    default_values: dict = DEFAULT_SLURM_MAIL_CONFIG,
) -> None:
    """Initialize the slurm-mail configuration file with default values if it does not exist.

    Args:
        config_path: Configuration file path. Defaults to SLURM_MAIL_CONFIG_PATH.
        default_values: Default configuration values. Defaults to DEFAULT_SLURM_MAIL_CONFIG.

    Raises:
        MailOpsError: If an error occurs during configuration file initialization.
    """
    if config_path.exists():
        _logger.warning(
            "Configuration file already exists: %s. Skipping initialization", config_path
        )
        return

    _logger.info("Configuration file not found: %s. Creating new configuration file", config_path)

    default_config = configparser.RawConfigParser()
    # Preserve camelCase keys, such as smtpServer
    default_config.optionxform = str  # pyright: ignore[reportAttributeAccessIssue]
    default_config.read_dict(default_values)
    _write_config_file(config_path, default_config)


def _write_config_file(config_path: Path, config: configparser.RawConfigParser) -> None:
    """Write configuration to file with appropriate permissions and ownership.

    Args:
        config_path: Configuration file path.
        config: ConfigParser object to write to the file.

    Raises:
        MailOpsError: If an error occurs during file writing or setting of permissions.
    """
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MailOpsError(f"Failed to create parent directories for {config_path}") from e

    # Write to temp file and atomically replace original
    swap = config_path.with_stem("." + config_path.stem).with_suffix(config_path.suffix + ".swp")

    try:
        with swap.open("w") as f:
            config.write(f)

        # Ensure slurm group has read access. Necessary for slurmctld to run MailProg=slurm-spool-mail
        swap.chmod(0o640)
        shutil.chown(swap, "root", "slurm")
        swap.replace(config_path)
    except OSError as e:
        raise MailOpsError(
            f"Failed to write, set permissions, ownership, or atomically replace config file {config_path}"
        ) from e
