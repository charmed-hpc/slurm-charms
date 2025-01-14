# Slurm charms

[![CI](https://github.com/charmed-hpc/slurm-charms/actions/workflows/ci.yaml/badge.svg)](https://github.com/charmed-hpc/slurm-charms/actions/workflows/ci.yaml/badge.svg)
[![Release](https://github.com/charmed-hpc/slurm-charms/actions/workflows/release.yaml/badge.svg)](https://github.com/charmed-hpc/slurm-charms/actions/workflows/release.yaml/badge.svg)
![GitHub License](https://img.shields.io/github/license/charmed-hpc/slurm-charms)
[![Matrix](https://img.shields.io/matrix/ubuntu-hpc%3Amatrix.org?logo=matrix&label=ubuntu-hpc)](https://matrix.to/#/#hpc:ubuntu.com)

[Juju](https://juju.is) charms for automating the Day 0 to Day 2 operations of the [Slurm workload manager](https://slurm.schedmd.com/overview.html) ⚖️🐧

The `slurm-charms` repository is a collection of charmed operators that enables you to easily deploy, configure, and manage the Slurm workload manager.
Here's the current charms in the collection:

* [`sackd`](./charms/sackd/): the authentication and credential kiosk daemon for Slurm.
* [`slurmctld`](./charms/slurmctld/): the central management daemon for Slurm.
* [`slurmd`](./charms/slurmd): the compute node daemon for Slurm.
* [`slurmdbd`](./charms/slurmdbd): the database daemon for Slurm.
* [`slurmrestd`](./charms/slurmrestd/): the REST API interface to Slurm.

## ✨ Getting started

To deploy the Slurm charms from [Charmhub](https://charmhub.io), you must be using Juju 3.x or greater.

```shell
juju deploy sackd --channel edge
juju deploy slurmctld --channel edge
juju deploy slurmd --channel edge
juju deploy slurmdbd --channel edge
juju deploy slurmrestd --channel edge
juju deploy mysql --channel 8.0/stable
juju deploy mysql-router slurmdbd-mysql-router --channel dpe/edge

juju integrate sackd:login-node slurmctld:login-node
juju integrate slurmctld:slurmd slurmd:slurmctld
juju integrate slurmctld:slurmdbd slurmdbd:slurmctld
juju integrate slurmctld:slurmrestd slurmrestd:slurmctld
juju integrate slurmdbd-mysql-router:backend-database mysql:database
juju integrate slurmdbd:database slurmdbd-mysql-router:database
```

## 🤔 What's next?

If you want to learn more about all the things you can do with the Slurm charms, here are some resources for you to explore:

* [Documentation](https://canonical-charmed-hpc.readthedocs-hosted.com/en/latest)
* [Open an issue](https://github.com/charmed-hpc/slurm-charms/issues/new?title=ISSUE+TITLE&body=*Please+describe+your+issue*)
* [Ask a question on Github](https://github.com/orgs/charmed-hpc/discussions/categories/q-a)

## 🛠️ Development

The project uses [tox](tox.wiki) as its command runner, which provides some useful commands that
will definitely help while hacking on the charms:

```shell
tox run -e fmt # Apply formatting standards to code.
tox run -e lint # Check code against coding style standards.
tox run -e type # Type checking.
tox run -e unit # Run unit tests.
```

We also have some integration tests in place, but be aware that it requires a fairly good amount
of computer resources to run them. We usually test with at least 4 cores and 16 GB of RAM, but feel
free to experiment!

```shell
tox run -e integration
```

If you're interested in contributing, take a look at our [contributing guidelines](./CONTRIBUTING.md).

## 🤝 Project and Community

The Slurm charms are a project of the [Ubuntu High-Performance Computing community](https://ubuntu.com/community/governance/teams/hpc).
Interested in contributing bug fixes, patches, documentation, or feedback? Want to join the Ubuntu HPC community? You’ve come to the right place 🤩

Here’s some links to help you get started with joining the community:

* [Ubuntu Code of Conduct](https://ubuntu.com/community/ethos/code-of-conduct)
* [Contributing guidelines](./CONTRIBUTING.md)
* [Join the conversation on Matrix](https://matrix.to/#/#hpc:ubuntu.com)
* [Get the latest news on Discourse](https://discourse.ubuntu.com/c/hpc/151)
* [Ask and answer questions on GitHub](https://github.com/orgs/charmed-hpc/discussions/categories/q-a)

## 📋 License

The Slurm charms are free software, distributed under the Apache Software License, version 2.0.
See the [Apache-2.0 LICENSE](./LICENSE) file for further details.

The Slurm workload manager is licensed under the GNU General Public License, version 2, or any later version.
See Slurm's [legal notice](https://slurm.schedmd.com/disclaimer.html) for further licensing information about Slurm.
