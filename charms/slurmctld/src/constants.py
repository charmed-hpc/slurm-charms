# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.

"""This module provides constants for the slurmctld-operator charm."""

SLURMCTLD_PORT = 6817
PROMETHEUS_EXPORTER_PORT = 9092

PEER_INTEGRATION_NAME = "slurmctld-peer"

CLUSTER_NAME_PREFIX = "charmed-hpc"

CHARM_MAINTAINED_CGROUP_CONF_PARAMETERS = {
    "constraincores": True,
    "constraindevices": True,
    "constrainramspace": True,
    "constrainswapspace": True,
}

CHARM_MAINTAINED_SLURM_CONF_PARAMETERS = {
    "authaltparameters": {"jwt_key": "/var/lib/slurm/checkpoint/jwt_hs256.key"},
    "authalttypes": ["auth/jwt"],
    "authtype": "auth/slurm",
    "credtype": "cred/slurm",
    "grestypes": ["gpu"],
    "healthcheckinterval": 600,
    "healthchecknodestate": ["any", "cycle"],
    "healthcheckprogram": "/usr/sbin/charmed-hpc-nhc-wrapper",
    "mailprog": "/usr/bin/mail.mailutils",
    "plugindir": ["/usr/lib/x86_64-linux-gnu/slurm-wlm"],
    "plugstackconfig": "/etc/slurm/plugstack.conf.d/plugstack.conf",
    "selecttype": "select/cons_tres",
    "selecttypeparameters": {"cr_cpu_memory": True},
    "slurmctldport": SLURMCTLD_PORT,
    "slurmdport": 6818,
    "statesavelocation": "/var/lib/slurm/checkpoint",
    "slurmdspooldir": "/var/lib/slurm/slurmd",
    "slurmctldlogfile": "/var/log/slurm/slurmctld.log",
    "slurmdlogfile": "/var/log/slurm/slurmd.log",
    "slurmdpidfile": "/var/run/slurmd.pid",
    "slurmctldpidfile": "/var/run/slurmctld.pid",
    "slurmuser": "slurm",
    "slurmduser": "root",
    "rebootprogram": "/usr/sbin/reboot --reboot",
}
