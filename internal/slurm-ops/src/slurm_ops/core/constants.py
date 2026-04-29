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

"""Constants used within the `slurm-ops` package."""

# Dynamically create the "node" label using the unit name and ID number.
# This "node" label matches nodes' registered names in Slurm. This relabeling
# makes it easier to match scraped `node-exporter` metrics with Slurm exporter metrics
# in Prometheus alert rules.
UNIT_TO_NODE_NAME_RELABEL_CONFIG = {
    "source_labels": ["juju_unit"],
    "target_label": "node",
    "regex": r"(\S+)\/(\d+)",
    "replacement": "${1}-${2}",
}

NODE_EXPORTER_COLLECTORS = ["systemd"]
NODE_EXPORTER_PLUGS = ["hardware-observe", "mount-observe", "network-observe", "system-observe"]
NODE_EXPORTER_PORT = 9100
NODE_EXPORTER_SCRAPE_CONFIG = {
    "job_name": "node-exporter",
    "metrics_path": "/metrics",
    "scrape_interval": "60s",
    "static_configs": [
        {"targets": [f"*:{NODE_EXPORTER_PORT}"]},
    ],
    "relabel_configs": [UNIT_TO_NODE_NAME_RELABEL_CONFIG],
}

SLURM_USER = "slurm"
SLURM_GROUP = SLURM_USER
SLURMD_USER = "root"
SLURMD_GROUP = SLURMD_USER
SLURMRESTD_USER = "slurmrestd"
SLURMRESTD_GROUP = SLURMRESTD_USER
