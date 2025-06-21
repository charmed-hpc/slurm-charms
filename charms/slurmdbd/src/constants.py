# Copyright 2024 Omnivector, LLC
# Copyright 2025 Vantage Compute Corporation
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

"""Slurmdbd Charm Constants."""

DB_URI_SECRET_LABEL = "db-uri"

PEER_RELATION = "slurmdbd-peer"

SLURMDBD_PORT = 6819

SLURM_ACCT_DB = "slurm_acct_db"
CHARM_MAINTAINED_PARAMETERS = {
    "DbdPort": f"{SLURMDBD_PORT}",
    "AuthType": "auth/slurm",
    "SlurmUser": "slurm",
    "PluginDir": ["/usr/lib/x86_64-linux-gnu/slurm-wlm"],
    "PidFile": "/var/run/slurmdbd/slurmdbd.pid",
    "LogFile": "/var/log/slurm/slurmdbd.log",
    "StorageType": "accounting_storage/mysql",
}
