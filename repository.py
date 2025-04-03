#!/usr/bin/env python

# Taken from https://opendev.org/openstack/sunbeam-charms/src/commit/5b37e0a6919668f23b8c7b148717714889fd4381/repository.py

"""CLI tool to execute an action on any charm managed by this repository."""

import argparse
import glob
import logging
import os
import shutil
import subprocess
import tomllib
import fnmatch
import sys
import io
import itertools
from pathlib import Path
from threading import Thread
from dataclasses import dataclass
from collections.abc import Iterable, Mapping
from typing import Any

import yaml

ROOT_DIR = Path(__file__).parent.resolve()
BUILD_PATH = ROOT_DIR / "_build"
CHARMS_PATH = ROOT_DIR / "charms"
PYPROJECT_FILE = "pyproject.toml"
CHARMCRAFT_FILE = "charmcraft.yaml"
LOCK_FILE = "uv.lock"
LIBS_CHARM_PATH = BUILD_PATH / "libs"


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class RepositoryError(Exception):
    """Raise if the tool could not execute correctly."""


###############################################
# Utility functions
###############################################
@dataclass(init=False)
class BuildTool:
    path: str

    def __init__(self, tool: str) -> None:
        if not (tool_path := shutil.which(tool)):
            raise RepositoryError(f"Binary `{tool}` not installed or not in the PATH")

        logger.debug(f"Using {tool} from `{tool_path}`")

        self.path = tool_path

    def run_command(self, args: [str], *popenargs, **kwargs):
        def reader(pipe):
            with pipe:
                for line in pipe:
                    line.replace(str(BUILD_PATH), str(CHARMS_PATH))
                    print(line, end="")

        kwargs["text"] = True
        args.insert(0, self.path)
        env = kwargs.pop("env", os.environ)
        env["COLOR"] = "1"
        with subprocess.Popen(
            args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
        ) as process:
            Thread(target=reader, args=[process.stdout]).start()
            Thread(target=reader, args=[process.stderr]).start()
            return_code = process.wait()

        if return_code != 0:
            raise subprocess.CalledProcessError(returncode=return_code, cmd=args)


UV = BuildTool("uv")
CHARMCRAFT = BuildTool("charmcraft")


@dataclass
class CharmLibrary:
    """Specification about a charm library"""

    charm: str
    name: str
    major_version: int
    minor_version: int

    @property
    def path(self) -> Path:
        """Get the path of this library on the `lib/charms` directory."""
        return Path(self.charm.replace("-", "_")) / f"v{self.major_version}" / (self.name + ".py")

    def as_charmcraft_lib(self) -> dict[str, str]:
        """Get this charm library on the format used in `charmcraft.yaml`."""
        return {
            "lib": f"{self.charm}.{self.name}",
            "version": f"{self.major_version}.{self.minor_version}",
        }

    @staticmethod
    def from_charmcraft_lib(info: dict[str, str]) -> "CharmLibrary":
        """Get the specification of a charm library from an entry on `charmcraft.yaml`."""
        charm, name = info["lib"].split(".", maxsplit=1)
        major_version, minor_version = info["version"].split(".", maxsplit=1)
        major_version, minor_version = int(major_version), int(minor_version)

        return CharmLibrary(
            charm=charm,
            name=name,
            major_version=major_version,
            minor_version=minor_version,
        )


@dataclass
class Charm:
    """Information used to build a charm."""

    metadata: dict[str, Any]
    path: Path
    libraries: [CharmLibrary]

    @property
    def name(self) -> str:
        """Get the name of the charm."""
        return str(self.path.name)

    @property
    def build_path(self) -> Path:
        """Get the directory path that the staged charm must have on the output build directory."""
        return BUILD_PATH / self.path.name

    @property
    def charm_path(self) -> Path:
        """Get the file path that the built charm must have on the output build directory."""
        return BUILD_PATH / f"{self.path.name}.charm"


@dataclass(init=False)
class Repository:
    """Information about the monorepo."""

    charms: [Charm]
    external_libraries: [CharmLibrary]
    internal_libraries: [CharmLibrary]

    def __init__(self) -> "Repository":
        """Load the monorepo information."""
        UV.run_command(["lock", "--quiet"])
        try:
            with (ROOT_DIR / PYPROJECT_FILE).open(mode="rb") as f:
                project = tomllib.load(f)
        except OSError:
            raise RepositoryError(f"Failed to read file `{ROOT_DIR / PYPROJECT_FILE}`.")

        try:
            external_libraries = [
                CharmLibrary.from_charmcraft_lib(entry)
                for entry in project["tool"]["repository"]["external-libraries"]
            ]
        except KeyError:
            external_libraries = []

        try:
            binary_packages = project["tool"]["repository"]["binary-packages"]
            with (ROOT_DIR / LOCK_FILE).open(mode="rb") as f:
                uv_lock = tomllib.load(f)

            resolved_binary_packages = {
                bin_pkg: package["version"]
                for bin_pkg in binary_packages
                for package in uv_lock["package"]
                if package["name"] == bin_pkg
            }
        except KeyError:
            external_libraries = []
        except StopIteration:
            raise RepositoryError(f"Could not find package {pkg} in the lock file.")
        except OSError:
            raise RepositoryError(f"Failed to read file `{ROOT_DIR / LOCK_FILE}`.")

        internal_libraries = []
        for charm in CHARMS_PATH.iterdir():
            path = charm / "lib"
            charm_name = charm.name.replace("-", "_")
            search_path = path / "charms" / charm_name
            for p in search_path.glob("**/*.py"):
                relpath = p.relative_to(path)
                name = relpath.stem
                major_version = int(relpath.parts[2][1:])
                internal_libraries.append(
                    CharmLibrary(
                        charm=charm.name,
                        name=name,
                        major_version=major_version,
                        # We don't need the minor version since the library is internal,
                        # so we always use the latest minor version
                        minor_version=-1,
                    )
                )
        charms = [
            load_charm(
                charm, external_libraries, internal_libraries, resolved_binary_packages, uv_lock
            )
            for charm in CHARMS_PATH.iterdir()
        ]

        self.charms = charms
        self.external_libraries = external_libraries
        self.internal_libraries = internal_libraries


def load_charm(
    charm: Path,
    external_libraries: [CharmLibrary],
    internal_libraries: [CharmLibrary],
    binary_packages: Mapping[str, str],
    uv_lock: Mapping[str, Any],
) -> Charm:
    try:
        with (charm / PYPROJECT_FILE).open(mode="rb") as f:
            project = tomllib.load(f)
    except OSError:
        raise RepositoryError(f"Failed to read file `{charm / PYPROJECT_FILE}`.")

    try:
        with (charm / CHARMCRAFT_FILE).open(mode="rb") as f:
            metadata = dict(yaml.safe_load(f))
    except OSError:
        raise RepositoryError(f"Failed to read file `{charm / CHARMCRAFT_FILE}`.")

    # Since the `lock` file only lists direct dependencies for a specific package,
    # we need to recursively collect all the dependencies in order to see which
    # dependencies need to be specified as binary packages.
    deps = set()
    pending = [charm.name]
    while pending:
        package = pending.pop()
        deps.add(package)
        for pkg_dep in next(
            (pkg.get("dependencies", []) for pkg in uv_lock["package"] if pkg["name"] == package)
        ):
            if pkg_dep["name"] not in deps:
                deps.add(pkg_dep["name"])
                pending.append(pkg_dep["name"])

    metadata["parts"]["charm"]["charm-binary-python-packages"] = [
        f"{package}=={version}" for package, version in binary_packages.items() if package in deps
    ]

    libraries = []
    try:
        for lib in project["tool"]["repository"]["libraries"]:
            lib_charm, lib_name = lib.split(".", maxsplit=1)
            charm_lib = next(
                filter(
                    lambda lib: lib.charm == lib_charm and lib.name == lib_name,
                    itertools.chain(internal_libraries, external_libraries),
                )
            )
            libraries.append(charm_lib)
    except StopIteration:
        raise RepositoryError(f"Unknown library `{lib}` on `{charm / PYPROJECT_FILE}`")
    except KeyError:
        pass

    return Charm(
        metadata=metadata,
        path=charm,
        libraries=libraries,
    )


def copy(src: Path, dest: Path):
    """Copy the src to dest.

    Only supports files.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)


def remove_dir_if_exists(dir: Path):
    """Removes the directory `dir` if it exists and it's a directory."""
    try:
        shutil.rmtree(dir)
    except FileNotFoundError:
        # Directory doesn't exist, so skip.
        pass


def stage_charm(
    charm: Charm,
    repository: Repository,
    dry_run: bool = False,
):
    """Copy the necessary files.

    Will copy internal and external libraries.
    """
    logger.info("Staging charm %s...", charm.path.name)
    if not dry_run:
        remove_dir_if_exists(charm.build_path)
        shutil.copytree(charm.path, charm.build_path, dirs_exist_ok=True)

        # Overrides the charmcraft.yaml instead of editing it. This avoids having
        # to load two times the same charm metadata to inject the correct value for
        # charm-binary-python-packages
        try:
            with open(charm.build_path / CHARMCRAFT_FILE, "wt") as f:
                yaml.safe_dump(charm.metadata, f, sort_keys=False)
        except OSError:
            raise RepositoryError(f"Failed to write file `{charm.build_path / CHARMCRAFT_FILE}`.")

    for lib in charm.libraries:
        src = LIBS_CHARM_PATH / "lib" / "charms" / lib.path
        dest = charm.build_path / "lib" / "charms" / lib.path
        logger.debug("Copying %s to %s", lib, dest)
        if not dry_run:
            copy(src, dest)

    if not dry_run:
        UV.run_command(
            [
                "--quiet",
                "export",
                "--package",
                charm.name,
                "--frozen",
                "--no-hashes",
                "--format=requirements-txt",
                "-o",
                str(charm.build_path / "requirements.txt"),
            ]
        )
    logger.info("Staged charm %s at %s.", charm.path.name, charm.build_path)


def stage_charms(
    charms: [Charm], repository: Repository, clean: bool = False, dry_run: bool = False
):
    """Stage the list of provided charms."""
    LIBS_CHARM = {
        "name": "libs",
        "type": "charm",
        "base": "ubuntu@24.04",
        "summary": "",
        "description": "",
        "parts": {"charm": {}},
        "platforms": {"amd64": None},
        "charm-libs": [lib.as_charmcraft_lib() for lib in repository.external_libraries],
    }
    if clean and not dry_run:
        remove_dir_if_exists(LIBS_CHARM_PATH)
    if not dry_run:
        LIBS_CHARM_PATH.mkdir(parents=True, exist_ok=True)

    try:
        if not dry_run:
            with (LIBS_CHARM_PATH / CHARMCRAFT_FILE).open(mode="w") as f:
                yaml.safe_dump(LIBS_CHARM, f)
    except OSError:
        raise RepositoryError(f"Failed to write file `{LIBS_CHARM_PATH / CHARMCRAFT_FILE}`.")

    if repository.external_libraries:
        logger.info("Fetching external libraries...")
        if not dry_run:
            CHARMCRAFT.run_command(["fetch-libs"], cwd=LIBS_CHARM_PATH)

    for lib in repository.internal_libraries:
        src = CHARMS_PATH / lib.charm / "lib" / "charms" / lib.path
        dest = LIBS_CHARM_PATH / "lib" / "charms" / lib.path
        logger.debug(f"Copying internal lib {src} to {dest}.")
        if not dry_run:
            copy(src, dest)

    for charm in charms:
        logger.info("Preparing charm %s", charm.path.name)
        if clean:
            clean_charm(charm, dry_run=dry_run)
        stage_charm(
            charm,
            repository,
            dry_run=dry_run,
        )


def validate_charm(charm: str, repository: Repository) -> Charm:
    """Validate the charm."""
    try:
        return next(filter(lambda c: c.name == charm, repository.charms))
    except StopIteration:
        raise RepositoryError(f"Unknown charm `{charm.name}`")


def clean_charm(
    charm: Charm,
    dry_run: bool = False,
):
    """Clean charm directory."""
    logger.debug(f"Removing {charm.build_path}")
    if not dry_run:
        shutil.rmtree(charm.build_path, ignore_errors=True)
        charm.charm_path.unlink(missing_ok=True)


def get_source_dirs(charms: [Charm], include_tests: bool = True) -> [str]:
    """Get all the source directories for the specified charms."""
    files = [
        file
        for charm in charms
        for file in (
            str(charm.path / "src"),
            str(charm.path / "tests") if include_tests else "",
        )
        if file
    ]
    return files


def uv_run(args: [str], *popenargs, **kwargs) -> str:
    """Run a command using the uv runner."""
    args = ["run", "--frozen", "--extra", "dev"] + args
    return UV.run_command(args, *popenargs, **kwargs)


###############################################
# Cli Definitions
###############################################
def _add_charm_argument(parser: argparse.ArgumentParser):
    parser.add_argument("charm", type=str, nargs="*", help="The charms to operate on.")


def main_cli():
    """Run the main CLI tool."""
    main_parser = argparse.ArgumentParser(description="Repository utilities.")
    main_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging."
    )
    subparsers = main_parser.add_subparsers(required=True, help="sub-command help")

    stage_parser = subparsers.add_parser("stage", help="Stage charm(s).")
    stage_parser.add_argument(
        "--clean",
        action="store_true",
        default=False,
        help="Clean the charm(s) first.",
    )
    stage_parser.add_argument("--dry-run", action="store_true", default=False, help="Dry run.")
    stage_parser.set_defaults(func=stage_cli)
    _add_charm_argument(stage_parser)

    build_parser = subparsers.add_parser("build", help="Build all the specified charms.")
    build_parser.set_defaults(func=build_cli)
    _add_charm_argument(build_parser)

    gen_token_parser = subparsers.add_parser(
        "generate-token", help="Generate Charmhub token to publish charms."
    )
    gen_token_parser.set_defaults(func=gen_token_cli)
    _add_charm_argument(gen_token_parser)

    clean_parser = subparsers.add_parser("clean", help="Clean charm(s).")
    clean_parser.add_argument("--dry-run", action="store_true", default=False, help="Dry run.")
    clean_parser.set_defaults(func=clean_cli)

    pythonpath_parser = subparsers.add_parser("pythonpath", help="Print the pythonpath.")
    pythonpath_parser.set_defaults(func=pythonpath_cli)

    fmt_parser = subparsers.add_parser("fmt", help="Apply formatting standards to code.")
    fmt_parser.set_defaults(func=fmt_cli)
    _add_charm_argument(fmt_parser)

    lint_parser = subparsers.add_parser("lint", help="Check code against coding style standards")
    lint_parser.add_argument(
        "--fix", action="store_true", default=False, help="Try to fix the lint err ors"
    )
    lint_parser.set_defaults(func=lint_cli)
    _add_charm_argument(lint_parser)

    type_parser = subparsers.add_parser("typecheck", help="Type checking with pyright.")
    type_parser.set_defaults(func=typecheck_cli)
    _add_charm_argument(type_parser)

    unit_test_parser = subparsers.add_parser("unit", help="Run unit tests.")
    unit_test_parser.set_defaults(func=unit_test_cli)
    _add_charm_argument(unit_test_parser)

    integration_test_parser = subparsers.add_parser("integration", help="Run integration tests.")
    integration_test_parser.add_argument(
        "rest", type=str, nargs="*", help="Arguments forwarded to pytest"
    )
    integration_test_parser.set_defaults(func=integration_tests_cli)

    args = main_parser.parse_args(args=None if sys.argv[1:] else ["--help"])
    level = logging.INFO
    if args.verbose:
        level = logging.DEBUG
    logger.setLevel(level)
    repository = Repository()
    context = vars(args)
    context["repository"] = repository
    charms = context.pop("charm", "")
    if not charms:
        context["charms"] = repository.charms
    else:
        context["charms"] = [validate_charm(charm, repository) for charm in charms]
    args.func(**context)


def stage_cli(
    charms: [Charm],
    repository: Repository,
    clean: bool = False,
    dry_run: bool = False,
    **kwargs,
):
    """Stage the specified charms into the build directory."""
    stage_charms(charms, repository, clean, dry_run)


def gen_token_cli(
    charms: [Charm],
    **kwargs,
):
    """Generate Charmhub token to publish charms."""
    CHARMCRAFT.run_command(
        ["login", "--export=.charmhub.secret"]
        + [f"--charm={charm.name}" for charm in charms]
        + [
            "--permission=package-manage-metadata",
            "--permission=package-manage-releases",
            "--permission=package-manage-revisions",
            "--permission=package-view-metadata",
            "--permission=package-view-releases",
            "--permission=package-view-revisions",
            "--ttl=31536000",  # 365 days
        ]
    )


def clean_cli(
    repository: Repository,
    dry_run: bool = False,
    **kwargs,
):
    """Clean all the build artifacts."""
    if not dry_run:
        shutil.rmtree(BUILD_PATH, ignore_errors=True)


def pythonpath_cli(repository: Repository, **kwargs):
    """Print the pythonpath."""
    print(LIBS_CHARM_PATH / "lib")


def fmt_cli(
    charms: [Charm],
    **kwargs,
):
    """Apply formatting standards to code."""
    files = get_source_dirs(charms)
    files.append(str(ROOT_DIR / "tests"))
    logging.info(f"Formatting directories {files} with ruff...")
    uv_run(["ruff", "format"] + files, cwd=ROOT_DIR)


def lint_cli(
    charms: [Charm],
    fix: bool,
    **kwargs,
):
    """Check code against coding style standards."""
    files = get_source_dirs(charms)
    files.append(str(ROOT_DIR / "tests"))
    logging.info("Target directories: %s", files)
    if fix:
        logging.info("Trying to automatically fix the lint errors.")
    logging.info("Running codespell...")
    uv_run(["codespell"] + (["-w"] if fix else []) + files, cwd=ROOT_DIR)
    logging.info("Running ruff...")
    uv_run(["ruff", "check"] + (["--fix"] if fix else []) + files, cwd=ROOT_DIR)


def typecheck_cli(
    charms: [Charm],
    repository: Repository,
    **kwargs,
):
    """Type checking with pyright."""
    stage_charms(charms, repository)

    for charm in charms:
        logger.info("Running pyright...")
        uv_run(
            ["pyright", str(charm.build_path / "src")],
            env={
                **os.environ,
                "PYTHONPATH": f"{charm.build_path}/src:{charm.build_path}/lib",
            },
        )


def unit_test_cli(
    charms: [Charm],
    repository: Repository,
    **kwargs,
):
    """Run unit tests."""
    stage_charms(charms, repository)

    uv_run(["coverage", "erase"])

    files = []

    for charm in charms:
        logger.info("Running unit tests for %s", charm.path.name)
        coverage_file = charm.build_path / ".coverage"
        uv_run(
            ["coverage", "erase"],
            env={**os.environ, "COVERAGE_FILE": str(coverage_file)},
        )
        uv_run(
            [
                "coverage",
                "run",
                "--source",
                str(charm.build_path / "src"),
                "-m",
                "pytest",
                "-v",
                "--tb",
                "native",
                "-s",
                str(charm.build_path / "tests" / "unit"),
            ],
            env={
                **os.environ,
                "PYTHONPATH": f"{charm.build_path}/src:{charm.build_path}/lib",
                "COVERAGE_FILE": str(coverage_file),
            },
        )
        if coverage_file.is_file():
            files.append(str(coverage_file))

    logger.info("Generating global results...")
    uv_run(["coverage", "combine"] + files)
    uv_run(["coverage", "report"])
    uv_run(["coverage", "xml", "-o", "cover/coverage.xml"])
    logger.info(f"XML report generated at {ROOT_DIR}/cover/coverage.xml")


def build_cli(
    charms: [Charm],
    repository: Repository,
    **kwargs,
):
    """Build all the specified charms."""
    stage_charms(charms, repository)

    for charm in charms:
        logger.info("Building the charm %s", charm.name)
        subprocess.run(
            "charmcraft -v pack".split(),
            cwd=charm.build_path,
            check=True,
        )

        charm_long_path = (
            charm.build_path
            / glob.glob(f"{charm.path.name}_*.charm", root_dir=charm.build_path)[0]
        )
        logger.info("Moving charm %s to %s", charm_long_path, charm.charm_path)

        charm.charm_path.unlink(missing_ok=True)
        copy(charm_long_path, charm.charm_path)
        charm_long_path.unlink()
        logger.info("Built charm %s", charm.charm_path)


def integration_tests_cli(
    charms: [Charm],
    repository: Repository,
    rest: [str],
    **kwargs,
):
    """Run integration tests."""
    stage_charms(charms, repository)

    local_charms = {}

    for charm in charms:
        local_charms[f"{charm.name.upper().replace("-", "_")}_DIR"] = charm.build_path

    uv_run(
        [
            "pytest",
            "-v",
            "-s",
            "--tb",
            "native",
            "--log-cli-level=INFO",
            "./tests/integration",
        ]
        + rest,
        env={"PYTHONPATH": LIBS_CHARM_PATH / "lib", **os.environ, **local_charms},
    )


if __name__ == "__main__":
    main_cli()
