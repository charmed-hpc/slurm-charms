<div align="center">

# slurmd operator

A [Juju](https://juju.is) operator for slurmd - the compute node daemon of [SLURM](https://slurm.schedmd.com/overview.html).

[![Charmhub Badge](https://charmhub.io/slurmd/badge.svg)](https://charmhub.io/slurmd)
[![CI](https://github.com/omnivector-solutions/slurmd-operator/actions/workflows/ci.yaml/badge.svg)](https://github.com/omnivector-solutions/slurmd-operator/actions/workflows/ci.yaml/badge.svg)
[![Release](https://github.com/omnivector-solutions/slurmd-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/omnivector-solutions/slurmd-operator/actions/workflows/release.yaml/badge.svg)
[![Matrix](https://img.shields.io/matrix/ubuntu-hpc%3Amatrix.org?logo=matrix&label=ubuntu-hpc)](https://matrix.to/#/#ubuntu-hpc:matrix.org)

</div>

## Features

The slurmd operator provides and manages the slurmd daemon. This operator provides the compute node service for machines enlisted as compute nodes in Charmed SLURM clusters.

## Usage

This operator should be used with Juju 3.x or greater.

#### Deploy a minimal Charmed SLURM cluster

```shell
$ juju deploy slurmctld --channel edge
$ juju deploy slurmd --channel edge
$ juju integrate slurmctld:slurmd slurmd:slurmctld
```

### Operations
This charm hardens and simplifies operations by codifying common administration operations as charm actions.

#### Partition Configuration
Specify partition parameters using the charm configuration, `partition-config`.

##### Use the `partition-config` to set custom partition parameters.
```bash
$ juju config slurmd partition-config="State=INACTIVE"
```

#### Node Configuration Parameters
You can get and set the node configuration using the `node-config` action.

##### Use the `node-config` action to get the node configuration for the unit.
```bash
$ juju run --quiet slurmd/0 node-config --format json | jq ".[].results.node.config"
"NodeName=juju-462521-4 NodeAddr=10.240.222.28 State=UNKNOWN RealMemory=64012 CPUs=12 ThreadsPerCore=2 CoresPerSocket=6 SocketsPerBoard=1"
```

##### Use the `node-config` action to set a custom weight value for the node.
```bash
$ juju run --quiet slurmd/0 node-config parameters="Weight=5000" --format json | jq ".[].results.node.config"
"NodeName=juju-462521-4 NodeAddr=10.240.222.28 State=UNKNOWN RealMemory=64012 CPUs=12 ThreadsPerCore=2 CoresPerSocket=6 SocketsPerBoard=1 Weight=5000"
```

## Project & Community

The slurmd operator is a project of the [Ubuntu HPC](https://discourse.ubuntu.com/t/high-performance-computing-team/35988) 
community. It is an open source project that is welcome to community involvement, contributions, suggestions, fixes, and 
constructive feedback. Interested in being involved with the development of the slurmd operator? Check out these links below:

* [Join our online chat](https://matrix.to/#/#ubuntu-hpc:matrix.org)
* [Contributing guidelines](./CONTRIBUTING.md)
* [Code of conduct](https://ubuntu.com/community/ethos/code-of-conduct)
* [File a bug report](https://github.com/omnivector-solutions/slurmctld-operator/issues)
* [Juju SDK docs](https://juju.is/docs/sdk)

## License

The slurmd operator is free software, distributed under the Apache Software License, version 2.0. See the [LICENSE](./LICENSE) file for more information.
