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

"""Manage node health check (nhc) installation on compute node."""

import logging
import subprocess
import tempfile
import textwrap
from pathlib import Path

from constants import NHC_CONFIG

import charms.operator_libs_linux.v0.apt as apt

_logger = logging.getLogger(__name__)


class NHCOpsError(Exception):
    """Exception raised when a NHC operation failed."""

    @property
    def message(self) -> str:
        """Return message passed as argument to exception."""
        return self.args[0]


def install() -> None:
    """Install NHC on compute node.

    Raises:
        subprocess.CalledProcessError: Raised if error is encountered during NHC install.
    """
    _logger.info("installing required packages to install Node Health Check (NHC)")

    try:
        apt.add_package("make")
    except (apt.PackageNotFoundError, apt.PackageError) as e:
        raise NHCOpsError(f"failed to install package `make`. reason: {e}")

    _logger.info("installing NHC")
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            env = {"LC_ALL": "C", "LANG": "C.UTF-8"}

            _logger.info("extracting NHC tarball")
            r = subprocess.check_output(
                [
                    "tar",
                    "--extract",
                    "--directory",
                    tmpdir,
                    "--file",
                    "lbnl-nhc-1.4.3.tar.gz",
                    "--strip",
                    "1",
                ],
                stderr=subprocess.STDOUT,
                text=True,
            )
            _logger.debug(r)

            _logger.info("building NHC with autotools")
            r = subprocess.check_output(
                ["./autogen.sh", "--prefix=/usr", "--sysconfdir=/etc", "--libexecdir=/usr/lib"],
                cwd=tmpdir,
                env=env,
                stderr=subprocess.STDOUT,
                text=True,
            )
            _logger.debug(r)

            _logger.info("testing NHC build")
            r = subprocess.check_output(
                ["make", "test"], cwd=tmpdir, env=env, stderr=subprocess.STDOUT, text=True
            )
            _logger.debug(r)

            _logger.info("installing NHC")
            r = subprocess.check_output(
                ["make", "install"], cwd=tmpdir, env=env, stderr=subprocess.STDOUT, text=True
            )
            _logger.debug(r)
        except subprocess.CalledProcessError as e:
            _logger.error("failed to install NHC. reason: %s", e)
            raise

    # Write the nhc.conf following NHC installation.
    generate_config()


def get_config() -> str:
    """Get the current NHC configuration.

    Raises:
        FileNotFoundError: Raised if `/etc/nhc/nhc.conf` is not found on machine.
    """
    target = Path("/etc/nhc/nhc.conf")
    try:
        return target.read_text()
    except FileNotFoundError:
        _logger.warning("%s not found", target)
        raise


def generate_config(nhc_config: str = "") -> None:
    """Generate new nhc.conf configuration file.

    Args:
        nhc_config: NHC configuration to override default.
    """
    try:
        Path("/etc/nhc/nhc.conf").write_text(NHC_CONFIG + nhc_config)
    except FileNotFoundError as e:
        _logger.error(f"error rendering nhc.conf: {e}")
        raise


def generate_wrapper(params: str) -> None:
    """Generate NHC wrapper for Slurm.

    Args:
        params: Parameters to pass to `nhc-wrapper`.
    """
    _logger.debug("generating /usr/sbin/charmed-hpc-nhc-wrapper")
    target = Path("/usr/sbin/charmed-hpc-nhc-wrapper")
    target.write_text(
        textwrap.dedent(
            f"""
            #!/usr/bin/env bash

            /usr/sbin/nhc-wrapper {params}
            """
        ).strip()
    )
    target.chmod(0o755)
