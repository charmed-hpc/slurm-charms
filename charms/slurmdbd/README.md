<div align="center">

# slurmdbd operator

A [Juju](https://juju.is) operator for slurmdbd - the [SLURM](https://slurm.schedmd.com/overview.html) database daemon.

[![Charmhub Badge](https://charmhub.io/slurmdbd/badge.svg)](https://charmhub.io/slurmdbd)
[![CI](https://github.com/omnivector-solutions/slurmdbd-operator/actions/workflows/ci.yaml/badge.svg)](https://github.com/omnivector-solutions/slurmdbd-operator/actions/workflows/ci.yaml/badge.svg)
[![Release](https://github.com/omnivector-solutions/slurmdbd-operator/actions/workflows/release.yaml/badge.svg)](https://github.com/omnivector-solutions/slurmdbd-operator/actions/workflows/release.yaml/badge.svg)
[![Matrix](https://img.shields.io/matrix/ubuntu-hpc%3Amatrix.org?logo=matrix&label=ubuntu-hpc)](https://matrix.to/#/#ubuntu-hpc:matrix.org)

</div>

## Features

The slurmdbd operator provides and manages the slurmdbd service. This operator provides that database daemon that slurmctld uses to store accounting data. The slurmdbd operator must be integrated with a database backend such as the [MySQL operator](https://charmhub.io/mysql).

## Usage

This operator should be used with Juju 3.x or greater.

#### Deploy a minimal Charmed SLURM cluster

```shell
$ juju deploy slurmctld --channel edge
$ juju deploy slurmd --channel edge
$ juju deploy slurmdbd --channel edge
$ juju deploy mysql --channel 8.0/edge
$ juju deploy mysql-router slurmdbd-mysql-router --channel dpe/edge
$ juju integrate slurmctld:slurmd slurmd:slurmctld
$ juju integrate slurmctld:slurmdbd slurmdbd:slurmctld
$ juju integrate slurmdbd-mysql-router:backend-database mysql:database
$ juju integrate slurmdbd:database slurmdbd-mysql-router:database
```

#### Use your own MySQL database with Slurmdbd
In the case you want to use your own mysql databse inplace of deploying MySQL with `juju`,
create the db-uri secret and set the appropriate charm config.

See example using dockerized mysql running on localhost.

##### 1) Create a MySQL Database
```bash
docker run --name mysql-slurmdbd \
    -e MYSQL_USER=testuser \
    -e MYSQL_PASSWORD=testpassword \
    -e MYSQL_DATABASE=slurm_acct_db \
    -e MYSQL_ALLOW_EMPTY_PASSWORD=true \
    -p 3306:3306 \
    -d mysql:8.4
```

##### 2) Add Juju Infrastructure
```
ip=`hostname -i`

juju add-model mysql-testing

secret_id=`juju add-secret db-uri db-uri="mysql://testuser:testpassword@$ip:3306/slurm_acct_db"`

juju deploy slurmdbd --config db-uri-secret-id=$secret_id
juju deploy slurmctld --channel edge
juju deploy slurmd --channel edge

juju grant-secret db-uri slurmdbd

juju relate slurmctld slurmdbd
juju relate slurmctld slurmd
```

## Project & Community

The slurmdbd operator is a project of the [Ubuntu HPC](https://discourse.ubuntu.com/t/high-performance-computing-team/35988) 
community. It is an open source project that is welcome to community involvement, contributions, suggestions, fixes, and 
constructive feedback. Interested in being involved with the development of the slurmdbd operator? Check out these links below:

* [Join our online chat](https://matrix.to/#/#ubuntu-hpc:matrix.org)
* [Contributing guidelines](./CONTRIBUTING.md)
* [Code of conduct](https://ubuntu.com/community/ethos/code-of-conduct)
* [File a bug report](https://github.com/omnivector-solutions/slurmctld-operator/issues)
* [Juju SDK docs](https://juju.is/docs/sdk)

## License

The slurmdbd operator is free software, distributed under the Apache Software License, version 2.0. See the [LICENSE](./LICENSE) file for more information.
