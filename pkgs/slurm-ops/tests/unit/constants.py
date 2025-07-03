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

SLURM_APT_INFO = Template(
    textwrap.dedent(
        """
        Desired=Unknown/Install/Remove/Purge/Hold
        | Status=Not/Inst/Conf-files/Unpacked/halF-conf/Half-inst/trig-aWait/Trig-pend
        |/ Err?=(none)/Reinst-required (Status,Err: uppercase=bad)
        ||/ Name           Version          Architecture Description
        +++-==============-================-============-=================================
        ii  $service       23.11.7-2ubuntu1 amd64        SLURM daemon
        """
    )
)

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

EXAMPLE_ACCT_GATHER_CONFIG = """#
# `acct_gather.conf` file generated at 2024-09-18 15:10:44.652017 by slurmutils.
#
energyipmifrequency=1
energyipmicalcadjustment=yes
energyipmipowersensors=node=16,19;socket1=19,26;knc=16,19
energyipmiusername=testipmiusername
energyipmipassword=testipmipassword
energyipmitimeout=10
profilehdf5dir=/mydir
profilehdf5default=all
profileinfluxdbdatabase=acct_gather_db
profileinfluxdbdefault=all
profileinfluxdbhost=testhostname
profileinfluxdbpass=testpassword
profileinfluxdbrtpolicy=testpolicy
profileinfluxdbuser=testuser
profileinfluxdbtimeout=10
infinibandofedport=0
sysfsinterfaces=enp0s1
"""

EXAMPLE_CGROUP_CONFIG = """#
# `cgroup.conf` file generated at 2024-09-18 15:10:44.652017 by slurmutils.
#
constraincores=yes
constraindevices=yes
constrainramspace=yes
constrainswapspace=yes
"""

EXAMPLE_GRES_CONFIG = """#
# `gres.conf` file generated at 2024-12-10 14:17:35.161642 by slurmutils.
#
autodetect=nvml
name=gpu type=gp100 file=/dev/nvidia0 cores=0,1
name=gpu type=gp100 file=/dev/nvidia1 cores=0,1
name=gpu type=p6000 file=/dev/nvidia2 cores=2,3
name=gpu type=p6000 file=/dev/nvidia3 cores=2,3
name=gpu nodename=juju-c9c6f-[1-10] type=rtx file=/dev/nvidia[0-3] count=8G
name=mps count=200 file=/dev/nvidia0
name=mps count=200 file=/dev/nvidia1
name=mps count=100 file=/dev/nvidia2
name=mps count=100 file=/dev/nvidia3
name=bandwidth type=lustre count=4G flags=countonly
"""

EXAMPLE_OCI_CONFIG = """#
# `oci.conf` file generated at 2024-09-18 19:05:45.723019 by slurmutils.
#
ignorefileconfigjson=true
envexclude="^(SLURM_CONF|SLURM_CONF_SERVER)="
runtimeenvexclude="^(SLURM_CONF|SLURM_CONF_SERVER)="
runtimerun="singularity exec --userns %r %@"
runtimekill="kill -s SIGTERM %p"
runtimedelete="kill -s SIGKILL %p"
"""

EXAMPLE_SLURM_CONFIG = """#
# `slurm.conf` file generated at 2024-01-30 17:18:36.171652 by slurmutils.
#
slurmctldhost=juju-c9fc6f-0(10.152.28.20)
slurmctldhost=juju-c9fc6f-1(10.152.28.100)

clustername=charmed-hpc
authtype=auth/slurm
epilog=/usr/local/slurm/epilog
prolog=/usr/local/slurm/prolog
firstjobid=65536
inactivelimit=120
jobcomptype=jobcomp/filetxt
jobcomploc=/var/log/slurm/jobcomp
killwait=30
maxjobcount=10000
minjobage=3600
plugindir=/usr/local/lib:/usr/local/slurm/lib
returntoservice=0
schedulertype=sched/backfill
slurmctldlogfile=/var/log/slurm/slurmctld.log
slurmdlogfile=/var/log/slurm/slurmd.log
slurmctldport=7002
slurmdport=7003
slurmdspooldir=/var/spool/slurmd.spool
statesavelocation=/var/spool/slurm.state
tmpfs=/tmp
waittime=30

#
# node configurations
#
nodename=juju-c9fc6f-2 nodeaddr=10.152.28.48 cpus=1 realmemory=1000 tmpdisk=10000
nodename=juju-c9fc6f-3 nodeaddr=10.152.28.49 cpus=1 realmemory=1000 tmpdisk=10000
nodename=juju-c9fc6f-4 nodeaddr=10.152.28.50 cpus=1 realmemory=1000 tmpdisk=10000
nodename=juju-c9fc6f-5 nodeaddr=10.152.28.51 cpus=1 realmemory=1000 tmpdisk=10000

#
# down node configurations
#
downnodes=juju-c9fc6f-5 state=down reason="Maintenance Mode"

#
# partition configurations
#
partitionname=default maxtime=30 maxnodes=10 state=up
partitionname=batch nodes=juju-c9fc6f-2,juju-c9fc6f-3,juju-c9fc6f-4,juju-c9fc6f-5 minnodes=4 maxtime=120 allowgroups=admin
"""

EXAMPLE_SLURMDBD_CONFIG = """#
# `slurmdbd.conf` file generated at 2024-01-30 17:18:36.171652 by slurmutils.
#
archiveevents=yes
archivejobs=yes
archiveresvs=yes
archivesteps=no
archivetxn=no
archiveusage=no
archivescript=/usr/sbin/slurm.dbd.archive
authinfo=use_client_ids
authtype=auth/slurm
authalttypes=auth/jwt
authaltparameters=jwt_key=16549684561684@
dbdhost=slurmdbd-0
dbdbackuphost=slurmdbd-1
debuglevel=info
plugindir=/all/these/cool/plugins
purgeeventafter=1month
purgejobafter=12month
purgeresvafter=1month
purgestepafter=1month
purgesuspendafter=1month
purgetxnafter=12month
purgeusageafter=24month
logfile=/var/log/slurmdbd.log
pidfile=/var/run/slurmdbd.pid
slurmuser=slurm
storagepass=supersecretpasswd
storagetype=accounting_storage/mysql
storageuser=slurm
storagehost=127.0.0.1
storageport=3306
storageloc=slurm_acct_db
"""
