<div align="center">

# sackd operator

A [Juju](https://juju.is) operator for sackd - the login node daemon of [Slurm](https://slurm.schedmd.com/overview.html).

[![Charmhub Badge](https://charmhub.io/sackd/badge.svg)](https://charmhub.io/sackd)
[![Matrix](https://img.shields.io/matrix/ubuntu-hpc%3Amatrix.org?logo=matrix&label=ubuntu-hpc)](https://matrix.to/#/#ubuntu-hpc:matrix.org)

</div>

## Features

The sackd operator provides and manages the sackd daemon. This daemon provides the login node service for machines enlisted as login nodes in Charmed Slurm clusters.

## Usage

This operator should be used with Juju 3.x or greater.

#### Deploy a minimal Charmed Slurm cluster with a login node

```shell
$ juju deploy slurmctld --channel edge
$ juju deploy slurmd --channel edge
$ juju deploy sackd --channel edge
$ juju integrate slurmctld:slurmd slurmd:slurmctld
$ juju integrate slurmctld:login-node sackd:slurmctld
```

## Project & Community

The sackd operator is a project of the [Ubuntu HPC](https://discourse.ubuntu.com/t/high-performance-computing-team/35988)
community. It is an open source project that is welcome to community involvement, contributions, suggestions, fixes, and
constructive feedback. Interested in being involved with development? Check out these links below:

* [Join our online chat](https://matrix.to/#/#ubuntu-hpc:matrix.org)
* [Contributing guidelines](./CONTRIBUTING.md)
* [Code of conduct](https://ubuntu.com/community/ethos/code-of-conduct)
* [File a bug report](https://github.com/charmed-hpc/slurm-charms/issues)
* [Juju SDK docs](https://juju.is/docs/sdk)

## License

The sackd operator is free software, distributed under the Apache Software License, version 2.0. See the [LICENSE](./LICENSE) file for more information.
