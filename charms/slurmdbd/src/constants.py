# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.
"""Constants."""
from pathlib import Path

_SNAP_COMMON = Path("/var/snap/slurm/common")

SLURM_USER = "root"
SLURM_GROUP = "root"

SLURMDBD_CONF_PATH = _SNAP_COMMON / "etc/slurm/slurmdbd.conf"
SPOOL_DIR = _SNAP_COMMON / "var/lib/slurm/slurmdbd"
SLURMDBD_DEFAULTS_FILE = _SNAP_COMMON / "etc/default/slurmdbd"
JWT_RSA_PATH = SPOOL_DIR / "jwt_hs256.key"

SLURM_ACCT_DB = "slurm_acct_db"

CHARM_MAINTAINED_PARAMETERS = {
    "DbdPort": "6819",
    "AuthType": "auth/munge",
    "AuthInfo": f'"socket={_SNAP_COMMON}/run/munge/munged.socket.2"',
    "SlurmUser": SLURM_USER,
    "PidFile": f"{_SNAP_COMMON}/run/slurmdbd.pid",
    "LogFile": f"{_SNAP_COMMON}/var/log/slurm/slurmdbd.log",
    "StorageType": "accounting_storage/mysql",
}
