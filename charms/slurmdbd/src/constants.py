# Copyright 2025 Vantage Compute Corporation
# Copyright 2024 Omnivector, LLC
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

"""Constants used within the `slurmdbd` charmed operator."""

DATABASE_INTEGRATION_NAME = "database"
PEER_INTEGRATION_NAME = "slurmdbd-peer"
SLURMDBD_INTEGRATION_NAME = "slurmctld"

SLURM_ACCT_DATABASE_NAME = "slurm_acct_db"
SLURMDBD_PORT = 6819

OVERRIDES_CONFIG_FILE = "slurmdbd.conf.overrides"
STORAGE_CONFIG_FILE = "slurmdbd.conf.storage"
DEFAULT_SLURMDBD_CONFIG = {
    "dbdport": SLURMDBD_PORT,
    "authtype": "auth/slurm",
    "slurmuser": "slurm",
    "plugindir": ["/usr/lib/x86_64-linux-gnu/slurm-wlm"],
    "pidfile": "/var/run/slurmdbd/slurmdbd.pid",
    "logfile": "/var/log/slurm/slurmdbd.log",
    "storagetype": "accounting_storage/mysql",
}
