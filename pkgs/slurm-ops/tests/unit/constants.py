# Copyright 2025-2026 Canonical Ltd.
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

"""Constants used within unit tests for the `slurm-ops` package."""

import grp
import os
import pwd
import textwrap
from string import Template

# `pyfakefs` doesn't have the ability to create fake users and groups.
FAKE_USER_UID = os.getuid()
FAKE_USER = pwd.getpwuid(FAKE_USER_UID).pw_name
FAKE_GROUP_GID = os.getgid()
FAKE_GROUP = grp.getgrgid(FAKE_GROUP_GID).gr_name

SLURM_KEY_BASE64 = "MTIzNDU2Nzg5MA=="

JWT_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAt3PLWkwUOeckDwyMpHgGqmOZhitC8KfOQY/zPWfo+up5RQXz
gVWqsTIt1RWynxIwCGeKYfVlhoKNDEDL1ZjYPcrrGBgMEC8ifqxkN4RC8bwwaGrJ
9Zf0kknPHI5AJ9Fkv6EjgAZW1lwV0uEE5kf0wmlgfThXfzwwGVHVwemE1EgUzdI/
rVxFP5Oe+mRM7kWdtXQrfizGhfmr8laCs+dgExpPa37mk7u/3LZfNXXSWYiaNtie
vax5BxmI4bnTIXxdTT4VP9rMxG8nSspVj5NSWcplKUANlIkMKiO7k/CCD/YzRzM0
0yZttiTvECG+rKy+KJd97dbtj6wSvbJ7cjfq2wIDAQABAoIBACNTfPkqZUqxI9Ry
CjMxmbb97vZTJlTJO4KMgb51X/vRYwDToIxrPq9YhlLeFsNi8TTtG0y5wI8iXJ7b
a2T6RcnAZX0CRHBpYy8Za0L1iR6bqoaw6asNU99Hr0ZEbj48qDXuhbOFhPtKSDmP
cy4U9SDqwdXbH540rN5zT8JDgXyPAVJpwgsShk7rhgOFGIPIZqQoxEjPV3jr1sbk
k7c39fJR6Kxywppn7flSmNX3v1LDu4NDIp0Llt1NlcKlbdy5XWEW9IbiIYi3JTpB
kMpkFQFIuUyledeFyVFPsP8O7Da2rZS6Fb1dYNWzh3WkDRiAwYgTspiYiSf4AAi4
TgrOmiECgYEA312O5bXqXOapU+S2yAFRTa8wkZ1iRR2E66NypZKVsv/vfe0bO+WQ
kI6MRmTluvOKsKe3JulJZpjbl167gge45CHnFPZxEODAJN6OYp+Z4aOvTYBWQPpO
A75AGSheL66PWe4d+ZGvxYCZB5vf4THAs8BsGlFK04RKL1vHADkUjHUCgYEA0kFh
2ei/NP8ODrwygjrpjYSc2OSH9tBUoB7y5zIfLsXshb3Fn4pViF9vl01YkJJ57kki
KQm7rgqCsFnKS4oUFbjDDFbo351m1e3XRbPAATIiqtJmtLoLoSWuhXpsCbneM5bB
xLhFmm8RcFC6ORPBE2WMTGYzTEKydhImvUo+8A8CgYEAssWpyjaoRgSjP68Nj9Rm
Izv1LoZ9kX3H1eUyrEw/Hk3ze6EbK/xXkStWID0/FTs5JJyHXVBX3BK5plQ+1Rqj
I4vy7Hc2FWEcyCWMZmkA+3RLqUbvQgBUEnDh0oDZqWYX+802FnpA6V08nbdnH1D3
v6Zhn0qzDcmSqobVJluJE8UCgYB93FO1/QSQtel1WqUlnhx28Z5um4bkcVtnKn+f
dDqEZkiq2qn1UfrXksGbIdrVWEmTIcZIKKJnkbUf2fAl/fb99ccUmOX4DiIkB6co
+2wBi0CDX0XKA+C4S3VIQ7tuqwvfd+xwVRqdUsVupXSEfFXExbIRfdBRY0+vLDhy
cYJxcwKBgQCK+dW+F0UJTQq1rDxfI0rt6yuRnhtSdAq2+HbXNx/0nwdLQg7SubWe
1QnLcdjnBNxg0m3a7S15nyO2xehvB3rhGeWSfOrHYKJNX7IUqluVLJ+lIwgE2eAz
94qOCvkFCP3pnm/MKN6/rezyOzrVJn7GbyDhcjElu+DD+WRLjfxiSw==
-----END RSA PRIVATE KEY-----
"""

SLURM_APT_INFO = Template(textwrap.dedent("""
        Desired=Unknown/Install/Remove/Purge/Hold
        | Status=Not/Inst/Conf-files/Unpacked/halF-conf/Half-inst/trig-aWait/Trig-pend
        |/ Err?=(none)/Reinst-required (Status,Err: uppercase=bad)
        ||/ Name           Version          Architecture Description
        +++-==============-================-============-=================================
        ii  $service       23.11.7-2ubuntu1 amd64        SLURM daemon
        """))

SLURM_SNAP_INFO_ACTIVE = """
name:      slurm
summary:   "Slurm: A Highly Scalable Workload Manager"
publisher: –
store-url: https://snapcraft.io/slurm
license:   Apache-2.0
description: |
    Slurm is an open source, fault-tolerant, and highly scalable cluster
    management and job scheduling system for large and small Linux clusters.
commands:
    - slurm.command1
    - slurm.command2
services:
    slurm.logrotate:                 oneshot, enabled, inactive
    slurm.slurm-prometheus-exporter: simple, disabled, inactive
    slurm.sackd:                     simple, disabled, active
    slurm.slurmctld:                 simple, disabled, active
    slurm.slurmd:                    simple, enabled, active
    slurm.slurmdbd:                  simple, disabled, active
    slurm.slurmrestd:                simple, disabled, active
channels:
    latest/stable:    –
    latest/candidate: 23.11.7 2024-06-26 (460) 114MB classic
    latest/beta:      ↑
    latest/edge:      23.11.7 2024-06-26 (459) 114MB classic
installed:          23.11.7             (x1) 114MB classic
"""

SLURM_SNAP_INFO_INACTIVE = """
name:      slurm
summary:   "Slurm: A Highly Scalable Workload Manager"
publisher: –
store-url: https://snapcraft.io/slurm
license:   Apache-2.0
description: |
    Slurm is an open source, fault-tolerant, and highly scalable cluster
    management and job scheduling system for large and small Linux clusters.
commands:
    - slurm.command1
    - slurm.command2
services:
    slurm.logrotate:                 oneshot, enabled, inactive
    slurm.slurm-prometheus-exporter: simple, disabled, inactive
    slurm.sackd:                     simple, disabled, inactive
    slurm.slurmctld:                 simple, disabled, inactive
    slurm.slurmd:                    simple, enabled, inactive
    slurm.slurmdbd:                  simple, disabled, inactive
    slurm.slurmrestd:                simple, disabled, inactive
channels:
    latest/stable:    –
    latest/candidate: 23.11.7 2024-06-26 (460) 114MB classic
    latest/beta:      ↑
    latest/edge:      23.11.7 2024-06-26 (459) 114MB classic
installed:          23.11.7             (x1) 114MB classic
"""

SLURM_SNAP_INFO_NOT_INSTALLED = """
name:      slurm
summary:   "Slurm: A Highly Scalable Workload Manager"
publisher: –
store-url: https://snapcraft.io/slurm
license:   Apache-2.0
description: |
    Slurm is an open source, fault-tolerant, and highly scalable cluster
    management and job scheduling system for large and small Linux clusters.
channels:
    latest/stable:    –
    latest/candidate: 23.11.7 2024-06-26 (460) 114MB classic
    latest/beta:      ↑
    latest/edge:      23.11.7 2024-06-26 (459) 114MB classic
"""

ULIMIT_CONFIG = """
* soft nofile  1048576
* hard nofile  1048576
* soft memlock unlimited
* hard memlock unlimited
* soft stack unlimited
* hard stack unlimited
"""

SLURMD_C_OUTPUT = """
NodeName=juju-03865c-2 CPUs=8 Boards=1 SocketsPerBoard=1 CoresPerSocket=8 ThreadsPerCore=1 RealMemory=15986
UpTime=0-18:21:26
"""

SCONTROL_SHOW_NODE_OUTPUT = r"""
{
  "nodes": [
    {
      "architecture": "x86_64",
      "burstbuffer_network_address": "",
      "boards": 1,
      "boot_time": {
        "set": true,
        "infinite": false,
        "number": 1768928133
      },
      "tls_cert_last_renewal": {
        "set": true,
        "infinite": false,
        "number": 0
      },
      "cert_flags": [],
      "cluster_name": "",
      "cores": 8,
      "specialized_cores": 0,
      "cpu_binding": 0,
      "cpu_load": 11,
      "free_mem": {
        "set": true,
        "infinite": false,
        "number": 525
      },
      "cpus": 8,
      "effective_cpus": 8,
      "specialized_cpus": "",
      "energy": {
        "average_watts": 0,
        "base_consumed_energy": 0,
        "consumed_energy": 0,
        "current_watts": {
          "set": true,
          "infinite": false,
          "number": 0
        },
        "previous_consumed_energy": 0,
        "last_collected": 0
      },
      "external_sensors": {},
      "extra": "",
      "power": {},
      "features": [
        "compute"
      ],
      "active_features": [
        "compute"
      ],
      "gpu_spec": "",
      "gres": "",
      "gres_drained": "N\/A",
      "gres_used": "",
      "instance_id": "",
      "instance_type": "",
      "last_busy": {
        "set": true,
        "infinite": false,
        "number": 1769027120
      },
      "mcs_label": "",
      "specialized_memory": 1024,
      "name": "compute-0",
      "next_state_after_reboot": [
        "INVALID"
      ],
      "address": "10.216.61.171",
      "hostname": "juju-cd456c-2",
      "state": [
        "DOWN",
        "DYNAMIC_NORM"
      ],
      "operating_system": "Linux 6.8.0-90-generic #91-Ubuntu SMP PREEMPT_DYNAMIC Tue Nov 18 14:14:30 UTC 2025",
      "owner": "",
      "partitions": [
        "compute"
      ],
      "port": 6818,
      "real_memory": 15986,
      "res_cores_per_gpu": 0,
      "comment": "",
      "reason": "Not responding",
      "reason_changed_at": {
        "set": true,
        "infinite": false,
        "number": 1769096589
      },
      "reason_set_by_user": "slurm",
      "resume_after": {
        "set": true,
        "infinite": false,
        "number": 0
      },
      "reservation": "",
      "alloc_memory": 0,
      "alloc_cpus": 0,
      "alloc_idle_cpus": 8,
      "tres_used": "",
      "tres_weighted": 0.0,
      "slurmd_start_time": {
        "set": true,
        "infinite": false,
        "number": 1769026890
      },
      "sockets": 1,
      "threads": 1,
      "temporary_disk": 0,
      "weight": 1,
      "topology": "",
      "tres": "cpu=8,mem=15986M,billing=8",
      "version": "25.11.0"
    }
  ],
  "last_update": {
    "set": true,
    "infinite": false,
    "number": 1769557962
  },
  "meta": {
    "plugin": {
      "type": "",
      "name": "",
      "data_parser": "data_parser\/v0.0.44",
      "accounting_storage": "accounting_storage\/slurmdbd"
    },
    "client": {
      "source": "\/dev\/pts\/1",
      "user": "ubuntu",
      "group": "ubuntu"
    },
    "command": [
      "show",
      "node"
    ],
    "slurm": {
      "version": {
        "major": "25",
        "micro": "0",
        "minor": "11"
      },
      "release": "25.11.0",
      "cluster": "charmed-hpc-jj6q"
    }
  },
  "errors": [],
  "warnings": []
}
"""
