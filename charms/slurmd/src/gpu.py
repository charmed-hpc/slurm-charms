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

"""Manage GPU driver installation on compute node."""

import logging

# ubuntu-drivers requires apt_pkg for package operations
import apt_pkg  # pyright: ignore [reportMissingImports]
import charms.operator_libs_linux.v0.apt as apt
import UbuntuDrivers.detect  # pyright: ignore [reportMissingImports]

_logger = logging.getLogger(__name__)


class GPUOpsError(Exception):
    """Exception raised when a GPU driver installation operation failed."""

    @property
    def message(self) -> str:
        """Return message passed as argument to exception."""
        return self.args[0]


class GPUDriverDetector:
    """Detects GPU driver and kernel packages appropriate for the current hardware."""

    def __init__(self):
        """Initialize detection interfaces."""
        apt_pkg.init()

    def _system_gpgpu_driver_packages(self) -> dict:
        """Detect the available GPGPU drivers for this node."""
        return UbuntuDrivers.detect.system_gpgpu_driver_packages()

    def _get_linux_modules_metapackage(self, driver) -> str:
        """Retrieve the modules metapackage for the combination of current kernel and given driver.

        For example, linux-modules-nvidia-535-server-aws for driver nvidia-driver-535-server
        """
        return UbuntuDrivers.detect.get_linux_modules_metapackage(apt_pkg.Cache(None), driver)

    def system_packages(self) -> list[str]:
        """Return a list of GPU drivers and kernel module packages for this node."""
        packages = self._system_gpgpu_driver_packages()

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
                modules_metapackage = self._get_linux_modules_metapackage(driver_package)

                # Add to list of packages to install
                install_packages += [driver_metapackage, modules_metapackage]

        return [p for p in install_packages if p]


def autoinstall() -> bool:
    """Autodetect available GPUs and install drivers.

    Returns:
        True if drivers were installed, False otherwise.

    Raises:
        GPUOpsError: Raised if error is encountered during package install.
    """
    _logger.info("detecting GPUs and installing drivers")
    detector = GPUDriverDetector()
    install_packages = detector.system_packages()

    if len(install_packages) == 0:
        _logger.info("no GPU drivers requiring installation")
        return False

    _logger.info("installing GPU driver packages: %s", install_packages)
    try:
        apt.add_package(install_packages)
    except (apt.PackageNotFoundError, apt.PackageError) as e:
        raise GPUOpsError(f"failed to install packages {install_packages}. reason: {e}")

    return True
