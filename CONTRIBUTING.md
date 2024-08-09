# Contributing to the slurm-charms repository

Do you want to contribute to the Slurm charms? You've come to
the right place then! __Here is how you can get involved.__

Please take a moment to review this document so that the contribution
process will be easy and effective for everyone. Also, please familiarise
yourself with the [Juju SDK](https://juju.is/docs/sdk) as it will help you
better understand how the Slurm charms are put together.

Following these guidelines helps you communicate that you respect the maintainers
managing the Slurm charms. In return, they will reciprocate that respect
while addressing your issue or assessing your submitted changes and/or features.

Have any questions? Feel free to ask them in the [Ubuntu High-Performance Computing
Matrix chat](https://matrix.to/#/#hpc:ubuntu.com).

### Table of Contents

* [Using the issue tracker](#using-the-issue-tracker)
* [Issues and Labels](#issues-and-labels)
* [Bug Reports](#bug-reports)
* [Enhancement Proposals](#enhancement-proposals)
* [Pull Requests](#pull-requests)
* [Discussions](#discussions)
* [Code Guidelines](#code-guidelines)
* [License](#license)

## Using the issue tracker

The issue tracker is the preferred way for tracking [bug reports](#bug-reports), [enhancement proposals](#enhancement-proposals),
and [submitted pull requests](#pull-requests), but please follow these guidelines for the issue tracker:

* Please __do not__ use the issue tracker for personal issues and/or support requests.
The [Discussions](#discussions) page is a better place to get help for personal support requests.

* Please __do not__ derail or troll issues. Keep the discussion on track and have respect for the other
users/contributors of the Slurm charms.

* Please __do not__ post comments consisting solely of "+1", ":thumbsup:", or something similar.
Use [GitHub's "reactions" feature](https://blog.github.com/2016-03-10-add-reactions-to-pull-requests-issues-and-comments/)
instead.
  * The maintainers of the Slurm charms reserve the right to delete comments
  that violate this rule.

* Please __do not__ repost or reopen issues that have been closed. Please either
submit a new issue or browser through previous issues.
  * The maintainers of Slurm charms reserve the right to delete issues
  that violate this rule.

## Issues and Labels

The issue tracker uses a variety of labels to help organize and identify issues.
Here is a list of some of these labels, and how the maintainers of the repository use them:

* `Type: Bug` - Issues reported in the source code that either produce errors or unexpected behavior.

* `Status: Confirmed` - Issues marked `Type: Bug` that have be confirmed to be reproducible on a separate system.

* `Type: Documentation` - Issues for improving or updating the documentation.
Can also be used for pull requests.

* `Type: Refactor` - Issues that pertain to improving the existing code base.

* `Type: Idea Bank` - Issues that pertain to proposing potential improvements to the code base.

* `Type: Enhancement` - Issues marked as an agreed upon enhancement to the code base. Can also be used for pull requests.

* `Statues: Help wanted` - Issues where we need help from the greater open source community to solve.

For a complete look at this repository's labels, see the
[project labels page](https://github.com/charmed-hpc/slurm-charms/labels).

## Bug Reports

A bug is a *demonstrable problem* that is caused by errors in the Slurm charms.
Good bug reports make the Slurm charms better, so
thank you for taking the time to report issues!

Guidelines for reporting bugs with the Slurm charms:

1. __Validate your issue__ &mdash; ensure that your issue is not being caused by either
a semantic or syntactic error in your environment.

2. __Use the GitHub issue search__ &mdash; check if the issue you are encountering has
already been reported by someone else.

3. __Check if the issue has already been fixed__ &mdash; try to reproduce your issue
using the latest version of the Slurm charms.

4. __Isolate the problem__ &mdash; the more pinpointed the issue with the Slurm charms
is, the easier it is to fix.

A good bug report should not leave others needing to chase you for more information.
Some common questions you should answer in your report include:

* What is your current environment?
* Were you able to reproduce the issue in another environment?
* Which commands/actions/configuration options/etc produce the issue?
* What was your expected outcome?

Please try to be as detailed as possible in your report. All these details will help the
maintainers quickly fix issues with the Slurm charms.

## Enhancement Proposals

The Charmed HPC core developers may already know what they want to add to the Slurm charms,
but they are always open to new ideas and potential improvements. GitHub Discussions is
a good place for discussing open-ended questions that pertain to the entire Charmed HPC
project, but more focused enhancement proposal discussions can start within the issue
tracker.

Please note that not all proposals may be incorporated into the the Slurm charms. Also, please
know that spamming the maintainers to incorporate something you want into the Slurm charms
will not improve the likelihood of being implemented; it may result in you receiving a
temporary ban from the repository.

## Pull Requests

Good pull requests &mdash; patches, improvements, new features &mdash;
are a huge help. Pull requests should remain focused and not contain commits not
related to what you are contributing.

__Ask first__ before embarking on any __significant__ pull request such as
implementing new features, refactoring methods, or incorporating new libraries;
otherwise, you risk spending a lot of time working on something that the Charmed HPC
core developers may not want to merge into the the Slurm charms! For trivial changes,
or contributions that do not require a large amount of time, you can go ahead and
open a pull request.

Adhering to the following process is the best way to get your contribution accepted into
the Slurm charms:

1. [Fork](https://help.github.com/articles/fork-a-repo/) the project, clone your fork,
   and configure the remotes:

   ```bash
   # Clone your fork of the repo into the current directory
   git clone https://github.com/<your-username>/slurm-charms.git

   # Navigate to the newly cloned directory
   cd slurm-charms

   # Assign the original repo to a remote called "upstream"
   git remote add upstream https://github.com/charmed-hpc/slurm-charms.git
   ```

2. If you cloned a while ago, pull the latest changes from the upstream slurm-charms repository:

   ```bash
   git checkout main
   git pull upstream main
   ```

3. Create a new topic branch (off the main project development branch) to
   contain your feature, change, or fix:

   ```bash
   git checkout -b <topic-branch-name>
   ```

4. Ensure that your changes pass all tests:

    ```bash
    # Apply formatting standards to code.
    tox run -e fmt

    # Check code against coding style standards.
    tox run -e lint

    # Run type checking.
    tox run -e type

    # Run unit tests.
    tox run -e unit

    # Run integration tests.
    tox run -e integration
    ```

5. Commit your changes in logical chunks to your topic branch.

   Our project follows the
   [Conventional Commits specification, version 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/).
   You can use Git's
   [interactive rebase](https://help.github.com/articles/about-git-rebase/) feature to
   tidy up your commits before pushing them to your origin branch.

6. Locally merge (or rebase) the upstream development branch into your topic branch:

   ```bash
   git pull [--rebase] upstream main
   ```

7. Push your topic branch up to your fork:

   ```bash
   git push origin <topic-branch-name>
   ```

8. [Open a Pull Request](https://help.github.com/articles/about-pull-requests/)
    with a clear title and description against the `main` branch.

## Discussions

GitHub Discussions is a great place to connect with other Charmed HPC users to
discuss potential enhancements, ask questions, and resolve issues. Charmed HPC users
should remain respectful of each other. Discussion moderators reserve the right to
suspend discussions and/or delete posts that do not follow this rule.

## Code guidelines

The following guidelines must be adhered to if you are writing code to be merged into the main code base:

### Monorepo

* We use a mono repository (monorepo) for tracking the development of the Slurm charms.
  All Slurm-related charms must be contributed to this repository and not
  broken out into its own standalone repository. Here's why:

  * We can test against the latest commit to the Slurm charms rather than
    pull what is currently published to edge on Charmhub.
    * Testing breaking changes is easier since we don't need to test between
      multiple separate PRs or branches on multiple repositories.
  * It's easier to enable CI testing for development branches. We can test
    the `experimental` development branch in the CI pipeline rather than needing
    to create a separate workflow file off of `main`.
  * We only need one branch protection to cover the Slurm charms.
  * We only need one set of integration tests for all the Slurm charms
    rather than multiple independent tests that repeat common operations.
  * We only need one extensive set of documentation rather than individual
    sets scoped per Slurm charm.

### Juju and charmed operators

* Adhere to the operator development best practices outlined in the [operator development styleguide](https://juju.is/docs/sdk/styleguide).

### Python

* Adhere to the Python code style guidelines outlined in [Python Enhancement Proposal 8](https://pep8.org/).

* Adhere to the Python docstring conventions outlined in
[Python Enhancement Proposal 257](https://www.python.org/dev/peps/pep-0257/).
  * *Docstrings must follow the
  [Google docstring format](https://github.com/google/styleguide/blob/gh-pages/pyguide.md#38-comments-and-docstrings)*.
license
## License

By contributing your code to the Slurm charms, you agree to license your contribution under the
[Apache Software License, version 2.0](https://www.apache.org/licenses/LICENSE-2.0.html).
