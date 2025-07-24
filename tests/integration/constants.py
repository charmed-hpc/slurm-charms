#!/usr/bin/env python3
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

"""Constants used within the Slurm charm integration tests."""

DEFAULT_SLURM_CHARM_CHANNEL = "latest/edge"
SACKD_APP_NAME = "login"
SLURMCTLD_APP_NAME = "controller"
SLURMD_APP_NAME = "compute"
SLURMDBD_APP_NAME = "database"
SLURMRESTD_APP_NAME = "rest-api"
SLURM_APPS = {
    SACKD_APP_NAME: "sackd",
    SLURMCTLD_APP_NAME: "slurmctld",
    SLURMD_APP_NAME: "slurmd",
    SLURMDBD_APP_NAME: "slurmdbd",
    SLURMRESTD_APP_NAME: "slurmrestd",
}

MYSQL_APP_NAME = "mysql"
INFLUXDB_APP_NAME = "influxdb"

DEFAULT_FILESYSTEM_CHARM_CHANNEL = "latest/edge"
MICROCEPH_APP_NAME = "microceph"
CEPHFS_SERVER_PROXY_APP_NAME = "cephfs-server-proxy"
FILESYSTEM_CLIENT_APP_NAME = "checkpoint"

SLURM_WAIT_TIMEOUT = 1200
