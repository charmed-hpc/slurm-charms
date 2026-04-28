# Copyright 2024-2026 Canonical Ltd.
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

"""Manage the Nvidia GPU lifecycle on individual compute nodes."""

__all__ = ["DCGM_EXPORTER_SCRAPE_CONFIG", "GPUOpsError", "NvidiaGPUManager"]

import logging
from functools import cached_property

# ubuntu-drivers requires apt_pkg for package operations
import apt_pkg  # pyright: ignore [reportMissingImports]
import UbuntuDrivers.detect  # pyright: ignore [reportMissingImports]
from charmed_hpc_libs.errors import SnapError
from charmed_hpc_libs.ops import DCGMManager
from charmlibs import apt
from slurm_ops import UNIT_TO_NODE_NAME_RELABEL_CONFIG

_logger = logging.getLogger(__name__)

DCGM_EXPORTER_PORT = 9101
DCGM_EXPORTER_SCRAPE_CONFIG = {
    "job_name": "dcgm-exporter",
    "metrics_path": "/metrics",
    "scrape_interval": "60s",
    "static_configs": [{"targets": [f"*:{DCGM_EXPORTER_PORT}"]}],
    "relabel_configs": [UNIT_TO_NODE_NAME_RELABEL_CONFIG],
}


class GPUOpsError(Exception):
    """Exception raised when a GPU driver installation operation failed."""

    @property
    def message(self) -> str:
        """Return message passed as argument to exception."""
        return self.args[0]


class NvidiaGPUManager:
    """Manage Nvidia GPU resources on Slurm compute nodes."""

    @cached_property
    def dcgm(self) -> DCGMManager:
        """Get the DCGM (Nvidia's Data Center GPU Manager) lifecycle manager."""
        return DCGMManager()

    def autoinstall(self) -> bool:
        """Autodetect available GPUs and install drivers.

        Returns:
            True if drivers were installed, False otherwise.

        Raises:
            GPUOpsError: Raised if error is encountered during package install.
        """
        _logger.info("detecting GPUs and installing drivers")

        apt_pkg.init()
        packages = UbuntuDrivers.detect.system_gpgpu_driver_packages()
        # Gather list of driver and kernel modules to install.
        install_packages = []
        for driver_package in packages:
            # Ignore drivers that are not recommended
            if packages[driver_package].get("recommended"):
                # Retrieve metapackage for this driver,
                # For example, nvidia-headless-no-dkms-535-server for nvidia-driver-535-server
                driver_metapackage = packages[driver_package]["metapackage"]

                # Retrieve modules metapackage for combination of current kernel and recommended driver,
                # For example, linux-modules-nvidia-535-server-aws
                modules_metapackage = UbuntuDrivers.detect.get_linux_modules_metapackage(
                    apt_pkg.Cache(None), driver_package
                )

                # Add to list of packages to install
                install_packages += [driver_metapackage, modules_metapackage]

        targets = [p for p in install_packages if p]
        if len(targets) == 0:
            _logger.info("no GPU drivers requiring installation")
            return False

        _logger.info("installing GPU driver packages: %s", targets)
        try:
            apt.add_package(targets)
        except (apt.PackageNotFoundError, apt.PackageError) as e:
            raise GPUOpsError(f"failed to install packages {targets}. reason: {e}")

        _logger.info("installing `dcgm` snap")
        try:
            self.dcgm.install()
            self.dcgm.set_dcgm_exporter_address(f":{DCGM_EXPORTER_PORT}")
            # Restart `dcgm-exporter` if it's already running to apply new port configuration.
            self.dcgm.exporter.restart()
            self.dcgm.exporter.enable()
        except SnapError as e:
            raise GPUOpsError(f"failed to install and start `dcgm-exporter` service. reason: {e}")

        return True
