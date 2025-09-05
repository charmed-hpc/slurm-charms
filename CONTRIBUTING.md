# Contributing to `slurm-charms`

Do you want to contribute to the `slurm-charms` repository? You've come to the right place then!
__Here is how you can get involved.__

Before you start working on your contribution, please familiarize yourself with the [Charmed
HPC project's contributing guide]. After you've gone through the main contributing guide,
you can use this guide for specific information on contributing to the `slurm-charms` repository.

Have any questions? Feel free to ask them in the [Ubuntu High-Performance Computing Matrix chat]
or on [GitHub Discussions].

[Charmed HPC project's contributing guide]: https://github.com/charmed-hpc/docs/blob/main/CONTRIBUTING.md
[Ubuntu High-Performance Computing Matrix chat]: https://matrix.to/#/#hpc:ubuntu.com
[GitHub Discussions]: https://github.com/orgs/charmed-hpc/discussions/categories/support

## Hacking on `slurm-charms`

This repository uses [just](https://github.com/casey/just) and [uv](https://github.com/astral-sh/uv) for development
which provide some useful commands that will help you while hacking on `slurm-charms`:

```shell
# Create a development environment
just env

# Upgrade uv.lock with the latest dependencies
just upgrade
```

Run `just help` to view the full list of available recipes.

### Using the monorepo

We use a mono repository (monorepo) for tracking the development of the Slurm charms.
All Slurm-related charms must be contributed to this repository and not broken out into
its own standalone repository.

Run `just repo` to view the full list of monorepo actions.

#### Why use a monorepo for `slurm-charms`?

- We can test against the latest commit to the Slurm charms rather than pull what is
  currently published to edge on Charmhub.
- Testing breaking changes is easier since we don't need to test between multiple separate
  pull requests or branches on multiple repositories.
- It's easier to enable CI testing for development branches. We can test the experimental
  development branch in the CI pipeline rather than needing to create a separate workflow
  file off of main.
- We only need one branch protection rule to cover the Slurm charms.
- We only need one set of integration tests for all the Slurm charms rather than multiple
  independent tests that repeat common operations.
- We only need one extensive set of documentation rather than individual sets scoped per
  Slurm charm.

### Before opening a pull request on the `slurm-charms` repository

Ensure that your changes pass all the existing tests, and that you have added tests
for any new features you're introducing in this changeset.

Your proposed changes will not be reviewed until your changes pass all the
required tests. You can run the required tests locally using `just`:

```shell
# Apply formatting standards to code
just repo fmt

# Check code against coding style standards
just repo lint

# Run static type checks
just repo typecheck

# Run unit tests
just repo unit

# Run minimally required integration test suite (matches CI)
just repo integration

# [Recommended] Run full integration tests suite
just repo integration -- --run-high-availability
```

Note: CI will check only `just repo integration`. However, we strongly recommend running
`just repo integration -- --run-high-availability` locally before submitting, as the full suite
includes additional coverage to catch more complex cases relating to charm scaling.

## Maintenance information

This repository uses Github Actions to handle some tasks related to the maintenance of the repository.

### Backporting commits

You can backport the commits of a PR into our list of maintained branches by adding the `backport`
label to a currently opened or already merged PR. This will automatically try to rebase the commits
into the branches by opening a PR against every maintained branch. Only merged PRs can be backported,
which means adding the `backport` label to an open PR will only trigger the backport when the PR
gets merged. The action will also make a comment on the original PR if the backport failed to be
applied, which will require manual intervention to resolve the merge conflict.

The list of maintained branches is defined in the [backport action][action].

[action]: .github/workflows/backport.yaml

## License information

By contributing to `slurm-charms`, you agree to license your contribution under
the Apache License 2.0 license.

### Adding a new file to `slurm-charms`

If you add a new source code file to the repository, add the following license header
as a comment to the top of the file with the copyright owner set to the organization
you are contributing on behalf of and the current year set as the copyright year.

```text
Copyright [yyyy] [name of copyright owner]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

### Updating an existing file in `slurm-charms`

If you are making changes to an existing file, and the copyright year is not the current year,
update the year range to include the current year. For example, if a file's copyright year is:

```text
Copyright 2023 Canonical Ltd.
```

and you make changes to that file in 2025, update the copyright year in the file to:

```text
Copyright 2023-2025 Canonical Ltd.
```
