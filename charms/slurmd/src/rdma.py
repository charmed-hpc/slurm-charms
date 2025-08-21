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

"""Manage RDMA packages on compute nodes."""

import logging
from pathlib import Path

import charms.operator_libs_linux.v0.apt as apt

_logger = logging.getLogger(__name__)


class RDMAOpsError(Exception):
    """Exception raised when an RDMA package installation operation failed."""

    @property
    def message(self) -> str:
        """Return message passed as argument to exception."""
        return self.args[0]


def _install_rdma() -> None:
    """Install the given list of packages."""
    install_packages = ["rdma-core", "infiniband-diags"]
    _logger.info("installing RDMA packages: %s", install_packages)
    try:
        apt.add_package(install_packages)
    except (apt.PackageNotFoundError, apt.PackageError) as e:
        raise RDMAOpsError(f"failed to install packages {install_packages}. reason: {e}")


def _override_ompi_conf() -> None:
    """Re-enable UCX/UCT transport protocol by overriding system OpenMPI configuration.

    Notes:
        The OpenMPI package from archive includes a Debian patch that disables UCX to silence
        warnings when running on systems without RDMA hardware. This leads to the less performant
        "ob1" method being selected on Infiniband-enabled systems. By default, OpenMPI selects UCX
        when Infiniband devices are available. This default functionality is restored here.

        See:
        * https://sources.debian.org/src/openmpi/4.1.4-3/debian/patches/no-warning-unused.patch/#L24
        * https://github.com/open-mpi/ompi/issues/8367
        * https://github.com/open-mpi/ompi/blob/v4.1.x/README#L763

    Todo:
        * This method may not be required in future. Recent versions of UCX do not seem to produce
          the warning messages in question. A bug is open with Debian to consider re-enabling UCX:
          https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1094805
    """
    conf = "/etc/openmpi/openmpi-mca-params.conf"
    _logger.info("enabling OpenMPI UCX transport in %s", conf)

    file = Path(conf)
    if not file.exists():
        _logger.warning("%s not found. skipping OpenMPI UCX enablement", file)
        return

    content = file.read_text().splitlines()
    for i, line in enumerate(content):
        if not line.startswith(("btl =", "pml =", "osc =")):
            continue

        parts = line.split()
        values = parts[2].strip().lstrip("^").split(",")
        values = [v for v in values if v not in ("uct", "ucx")]
        # Remove line entirely if all values removed, e.g. "pml = ^ucx"
        content[i] = f"{parts[0]} = ^{','.join(values)}" if values else ""

    file.write_text("\n".join(filter(None, content)) + "\n")


def install() -> None:
    """Install RDMA packages.

    Raises:
        RDMAOpsError: Raised if error is encountered during package install.
    """
    _install_rdma()
    _override_ompi_conf()
