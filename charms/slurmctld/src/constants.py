# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.

"""This module provides constants for the slurmctld-operator charm."""

PEER_RELATION = "slurmctld-peer"

CLUSTER_NAME_PREFIX = "charmed-hpc"

CHARM_MAINTAINED_CGROUP_CONF_PARAMETERS = {
    "ConstrainCores": "yes",
    "ConstrainDevices": "yes",
    "ConstrainRAMSpace": "yes",
    "ConstrainSwapSpace": "yes",
}

CHARM_MAINTAINED_SLURM_CONF_PARAMETERS = {
    "AuthAltParameters": {"jwt_key": "/var/lib/slurm/checkpoint/jwt_hs256.key"},
    "AuthAltTypes": ["auth/jwt"],
    "AuthInfo": {"socket": "/var/run/munge/munge.socket.2"},
    "AuthType": "auth/munge",
    "GresTypes": "gpu",
    "HealthCheckInterval": "600",
    "HealthCheckNodeState": ["ANY", "CYCLE"],
    "HealthCheckProgram": "/usr/sbin/charmed-hpc-nhc-wrapper",
    "MailProg": "/usr/bin/mail.mailutils",
    "PluginDir": ["/usr/lib/x86_64-linux-gnu/slurm-wlm"],
    "PlugStackConfig": "/etc/slurm/plugstack.conf.d/plugstack.conf",
    "SelectType": "select/cons_tres",
    "SelectTypeParameters": "CR_CPU_Memory",
    "SlurmctldPort": "6817",
    "SlurmdPort": "6818",
    "StateSaveLocation": "/var/lib/slurm/checkpoint",
    "SlurmdSpoolDir": "/var/lib/slurm/slurmd",
    "SlurmctldLogFile": "/var/log/slurm/slurmctld.log",
    "SlurmdLogFile": "/var/log/slurm/slurmd.log",
    "SlurmdPidFile": "/var/run/slurmd.pid",
    "SlurmctldPidFile": "/var/run/slurmctld.pid",
    "SlurmUser": "slurm",
    "SlurmdUser": "root",
    "RebootProgram": "/usr/sbin/reboot --reboot",
}
