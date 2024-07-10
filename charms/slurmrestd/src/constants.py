# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.
"""constants for slurmrestd-operator."""
from pathlib import Path

SNAP_COMMON = Path("/var/snap/slurm/common")

SLURMRESTD_GROUP_GID = 584788  # snap_daemon
SLURMRESTD_USER_UID = 584788  # snap_daemon

SLURM_CONF_PATH = SNAP_COMMON / "etc/slurm/slurm.conf"
