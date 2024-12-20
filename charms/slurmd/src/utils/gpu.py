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

"""Manage GPU driver installation on compute node."""

import logging
from importlib import import_module

import charms.operator_libs_linux.v0.apt as apt

_logger = logging.getLogger(__name__)


class GPUInstallError(Exception):
    """Exception raised when a GPU driver installation operation failed."""


class GPUDriverDetector:
    """Detects GPU driver and kernel packages appropriate for the current hardware."""

    def __init__(self):
        """Initialise detection attributes and interfaces."""
        # Install ubuntu-drivers tool and Python NVML bindings
        pkgs = ["ubuntu-drivers-common", "python3-pynvml"]
        try:
            apt.add_package(pkgs, update_cache=True)
        except (apt.PackageNotFoundError, apt.PackageError) as e:
            raise GPUInstallError(f"failed to install {pkgs} reason: {e}")

        # ubuntu-drivers requires apt_pkg for package operations
        self._detect = import_module("UbuntuDrivers.detect")
        self._apt_pkg = import_module("apt_pkg")
        self._apt_pkg.init()

    def _system_gpgpu_driver_packages(self) -> dict:
        """Detect the available GPGPU drivers for this node."""
        return self._detect.system_gpgpu_driver_packages()

    def _get_linux_modules_metapackage(self, driver) -> str:
        """Retrieve the modules metapackage for the combination of current kernel and given driver.

        e.g. linux-modules-nvidia-535-server-aws for driver nvidia-driver-535-server
        """
        return self._detect.get_linux_modules_metapackage(self._apt_pkg.Cache(None), driver)

    def system_packages(self) -> list:
        """Return a list of GPU drivers and kernel module packages for this node."""
        # Detect only GPGPU drivers. Not general purpose graphics drivers.
        packages = self._system_gpgpu_driver_packages()

        # Gather list of driver and kernel modules to install.
        install_packages = []
        for driver_package in packages:

            # Ignore drivers that are not recommended
            if packages[driver_package].get("recommended"):
                # Retrieve metapackage for this driver,
                # e.g. nvidia-headless-no-dkms-535-server for nvidia-driver-535-server
                driver_metapackage = packages[driver_package]["metapackage"]

                # Retrieve modules metapackage for combination of current kernel and recommended driver,
                # e.g. linux-modules-nvidia-535-server-aws
                modules_metapackage = self._get_linux_modules_metapackage(driver_package)

                # Add to list of packages to install
                install_packages += [driver_metapackage, modules_metapackage]

        # TODO: do we want to check for nvidia here and add nvidia-fabricmanager-535 libnvidia-nscq-535 in case of nvlink? This is suggested as a manual step at https://documentation.ubuntu.com/server/how-to/graphics/install-nvidia-drivers/#optional-step. If so, how do we get the version number "-535" robustly?

        # TODO: what if drivers install but do not require a reboot? Should we "modprobe nvidia" manually? Just always reboot regardless?

        # Filter out any empty results as returning
        return [p for p in install_packages if p]


def autoinstall() -> None:
    """Autodetect available GPUs and install drivers.

    Raises:
        GPUInstallError: Raised if error is encountered during package install.
    """
    _logger.info("detecting GPUs")
    detector = GPUDriverDetector()
    install_packages = detector.system_packages()

    if len(install_packages) == 0:
        _logger.info("no GPUs detected")
        return

    _logger.info(f"installing GPU driver packages: {install_packages}")
    try:
        apt.add_package(install_packages)
    except (apt.PackageNotFoundError, apt.PackageError) as e:
        raise GPUInstallError(f"failed to install packages {install_packages}. reason: {e}")


def get_gpus() -> dict:
    """Get the GPU devices on this node.

    Returns:
        A dict mapping model names to a list of device minor numbers. Model names are lowercase
        with whitespace replaced by underscores. For example:

        {'tesla_t4': [0, 1], 'l40s': [2, 3]}

        represents a node with two Tesla T4 GPUs at /dev/nvidia0 and /dev/nvidia1, and two L40S
        GPUs at /dev/nvidia2 and /dev/nvidia3.
    """
    gpu_info = {}

    # Return immediately if pynvml not installed...
    try:
        pynvml = import_module("pynvml")
    except ModuleNotFoundError:
        return gpu_info

    # ...or Nvidia drivers not loaded.
    try:
        pynvml.nvmlInit()
    except pynvml.NVMLError_DriverNotLoaded:
        return gpu_info

    gpu_count = pynvml.nvmlDeviceGetCount()
    # Loop over all detected GPUs, gathering info by model.
    for i in range(gpu_count):
        handle = pynvml.nvmlDeviceGetHandleByIndex(i)

        # Make model name lowercase and replace whitespace with underscores to turn into GRES-compatible format,
        # e.g. "Tesla T4" -> "tesla_t4", which can be added as "Gres=gpu:tesla_t4:1"
        # Aims to follow convention set by Slurm autodetect:
        # https://slurm.schedmd.com/gres.html#AutoDetect
        model = pynvml.nvmlDeviceGetName(handle)
        model = "_".join(model.split()).lower()

        # Number for device path, e.g. if device is /dev/nvidia0, returns 0
        minor_number = pynvml.nvmlDeviceGetMinorNumber(handle)

        try:
            # Add minor number to set of existing numbers for this model.
            gpu_info[model].add(minor_number)
        except KeyError:
            # This is the first time we've seen this model. Create a new entry.
            gpu_info[model] = {minor_number}

    pynvml.nvmlShutdown()
    return gpu_info
