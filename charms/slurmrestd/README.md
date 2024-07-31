<div align="center">

# slurmrestd operator

A [Juju](https://juju.is) operator for slurmrestd - the REST API interface to [SLURM](https://slurm.schedmd.com/overview.html).

[![Charmhub Badge](https://charmhub.io/slurmrestd/badge.svg)](https://charmhub.io/slurmrestd)
[![CI](https://github.com/omnivector-solutions/slurmrestd-operator/actions/workflows/ci.yaml/badge.svg)](https://github.com/omnivector-solutions/slurmrestd-operator/actions/workflows/ci.yaml/badge.svg)
[![Release](https://github.com/omnivector-solutions/slurmrestd-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/omnivector-solutions/slurmrestd-operator/actions/workflows/release.yaml/badge.svg)
[![Matrix](https://img.shields.io/matrix/ubuntu-hpc%3Amatrix.org?logo=matrix&label=ubuntu-hpc)](https://matrix.to/#/#ubuntu-hpc:matrix.org)

</div>

## Features

The slurmrestd operator provides the slurmrestd service. This operator provides a REST API for interfacing with the SLURM
workload manager. Rather than interfacing with SLURM via cluster head nodes, slurmrestd enables submitting batch jobs
via HTTP requests over a network.

## Usage

This operator should be used with Juju 3.x or greater.

#### Deploy a minimal Charmed SLURM cluster with slurmrestd

```shell
$ juju deploy slurmrestd --channel edge
$ juju deploy slurmctld --channel edge
$ juju deploy slurmd --channel edge
$ juju deploy slurmdbd --channel edge
$ juju deploy mysql --channel 8.0/edge
$ juju deploy mysql-router slurmdbd-mysql-router --channel dpe/edge
$ juju integrate slurmctld:slurmd slurmd:slurmctld
$ juju integrate slurmctld:slurmdbd slurmdbd:slurmctld
$ juju integrate slurmctld:slurmrestd slurmrestd:slurmctld
$ juju integrate slurmdbd-mysql-router:backend-database mysql:database
$ juju integrate slurmdbd:database slurmdbd-mysql-router:database
```

## Project & Community

The slurmrestd operator is a project of the [Ubuntu HPC](https://discourse.ubuntu.com/t/high-performance-computing-team/35988) 
community. It is an open source project that is welcome to community involvement, contributions, suggestions, fixes, and 
constructive feedback. Interested in being involved with the development of the slurmrestd operator? Check out these links below:

* [Join our online chat](https://matrix.to/#/#ubuntu-hpc:matrix.org)
* [Contributing guidelines](./CONTRIBUTING.md)
* [Code of conduct](https://ubuntu.com/community/ethos/code-of-conduct)
* [File a bug report](https://github.com/omnivector-solutions/slurmrestd-operator/issues)
* [Juju SDK docs](https://juju.is/docs/sdk)

## License

The slurmrestd operator is free software, distributed under the Apache Software License, version 2.0. See the [LICENSE](./LICENSE) file for more information.
