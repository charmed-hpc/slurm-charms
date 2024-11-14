# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.

"""Constants."""

SLURM_ACCT_DB = "slurm_acct_db"
CHARM_MAINTAINED_PARAMETERS = {
    "DbdPort": "6819",
    "AuthType": "auth/munge",
    "AuthInfo": {"socket": "/var/run/munge/munge.socket.2"},
    "SlurmUser": "slurm",
    "PluginDir": ["/usr/lib/x86_64-linux-gnu/slurm-wlm"],
    "PidFile": "/var/run/slurmdbd.pid",
    "LogFile": "/var/log/slurm/slurmdbd.log",
    "StorageType": "accounting_storage/mysql",
}
