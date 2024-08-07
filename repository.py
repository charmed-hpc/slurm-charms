#!/usr/bin/env python

# Taken from https://opendev.org/openstack/sunbeam-charms/src/commit/5b37e0a6919668f23b8c7b148717714889fd4381/repository.py

"""CLI tool to execute an action on any charm managed by this repository."""

import argparse
import glob
import logging
import os
import pathlib
import shutil
import subprocess
from dataclasses import dataclass

import yaml

ROOT_DIR = pathlib.Path(__file__).parent
EXTERNAL_LIB_DIR = ROOT_DIR / "external" / "lib"
BUILD_PATH = ROOT_DIR / "_build"
BUILD_FILE = "build.yaml"


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


###############################################
# Utility functions
###############################################
@dataclass
class SlurmCharm:
    """Information used to build a Slurm charm on the tox pipeline."""
    path: pathlib.Path
    external_libraries: list[str]
    internal_libraries: list[str]
    templates: list[str]

    @classmethod
    def load(cls, path: pathlib.Path) -> "SlurmCharm":
        """Load this charm from a path to its `build.yaml` file."""
        with path.open() as f:
            data = yaml.safe_load(f)
            return cls(
                path=path.parent,
                external_libraries=data.get("external-libraries", []),
                internal_libraries=data.get("internal-libraries", []),
                templates=data.get("templates", []),
            )

    @property
    def build_path(self) -> pathlib.Path:
        """Get the directory path that the staged charm must have on the output build directory."""
        return BUILD_PATH / self.path.name

    @property
    def charm_path(self) -> pathlib.Path:
        """Get the file path that the built charm must have on the output build directory."""
        return BUILD_PATH / f"{self.path.name}.charm"


def _library_to_path(library: str) -> pathlib.Path:
    split = library.split(".")
    if len(split) != 4:
        raise ValueError(f"Invalid library: {library}")
    return pathlib.Path("/".join(split) + ".py")


def validate_charm(
    charm: str,
    internal_libraries: dict[str, pathlib.Path],
    external_libraries: dict[str, pathlib.Path],
    templates: dict[str, pathlib.Path],
) -> SlurmCharm:
    """Validate the charm."""
    path = ROOT_DIR / "charms" / charm
    if not path.exists():
        raise ValueError(f"Charm {charm} does not exist.")
    build_file = path / BUILD_FILE
    if not build_file.exists():
        raise ValueError(f"Charm {charm} does not have a build file.")
    charm_build = load_charm(charm)

    for library in charm_build.external_libraries:
        if library not in external_libraries:
            raise ValueError(f"Charm {charm} has invalid external library: {library} not found.")
    for library in charm_build.internal_libraries:
        if library not in internal_libraries:
            raise ValueError(f"Charm {charm} has invalid internal library: {library} not found.")
    for template in charm_build.templates:
        if template not in templates:
            raise ValueError(f"Charm {charm} has invalid template: {template} not found.")
    return charm_build


def load_external_libraries() -> dict[str, pathlib.Path]:
    """Load the external libraries."""
    path = EXTERNAL_LIB_DIR
    return {str(p.relative_to(path))[:-3].replace("/", "."): p for p in path.glob("**/*.py")}


def load_internal_libraries() -> dict[str, pathlib.Path]:
    """Load the internal libraries."""
    charms = list((ROOT_DIR / "charms").iterdir())
    libraries = {}
    for charm in charms:
        path = charm / "lib"
        search_path = path / "charms" / charm.name.replace("-", "_")
        libraries.update(
            {
                str(p.relative_to(path))[:-3].replace("/", "."): p
                for p in search_path.glob("**/*.py")
            }
        )
    return libraries


def load_templates() -> dict[str, pathlib.Path]:
    """Load the templates."""
    path = ROOT_DIR / "templates"
    return {str(p.relative_to(path)): p for p in path.glob("**/*")}


def list_charms() -> list[str]:
    """List the available charms."""
    return [p.name for p in (ROOT_DIR / "charms").iterdir() if p.is_dir()]


def load_charm(charm: str) -> SlurmCharm:
    """Load the charm build file."""
    path = ROOT_DIR / "charms" / charm / BUILD_FILE
    return SlurmCharm.load(path)


def copy(src: pathlib.Path, dest: pathlib.Path):
    """Copy the src to dest.

    Only supports files.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)


def stage_charm(
    charm: SlurmCharm,
    internal_libraries: dict[str, pathlib.Path],
    external_libraries: dict[str, pathlib.Path],
    templates: dict[str, pathlib.Path],
    dry_run: bool = False,
):
    """Copy the necessary files.

    Will copy external libraries templates.
    """
    logger.info(f"Staging charm {charm.path.name}.")
    if not dry_run:
        shutil.copytree(charm.path, charm.build_path, dirs_exist_ok=True)
    for library in charm.external_libraries:
        path = external_libraries[library]
        library_path = path.relative_to(EXTERNAL_LIB_DIR)
        dest = charm.build_path / "lib" / library_path
        if not dest.exists():
            logger.debug(f"Copying {library} to {dest}")
            if dry_run:
                continue
            copy(path, dest)
    for library in charm.internal_libraries:
        path = internal_libraries[library]
        library_path = _library_to_path(library)
        dest = charm.build_path / "lib" / library_path
        if not dest.exists():
            logger.debug(f"Copying {library} to {dest}")
            if dry_run:
                continue
            copy(path, dest)
    for template in charm.templates:
        path = templates[template]
        dest = charm.build_path / "src" / "templates" / template
        if not dest.exists():
            logger.debug(f"Copying {template} to {dest}")
            if dry_run:
                continue
            copy(path, dest)
    logger.info(f"Charm {charm.path.name} staged at {charm.build_path}.")


def clean_charm(
    charm: SlurmCharm,
    dry_run: bool = False,
):
    """Clean charm directory.

    Will remove the external libraries and templates.
    """
    logger.debug(f"Removing {charm.build_path}")
    if not dry_run:
        shutil.rmtree(charm.build_path, ignore_errors=True)
        charm.charm_path.unlink(missing_ok=True)


def get_source_dirs(slurm_charms: [str], include_tests: bool = True) -> [str]:
    """Get all the source directories for the specified charms."""
    charms_dir = ROOT_DIR / "charms"
    files = [
        file
        for charm in slurm_charms
        for file in (
            str(charms_dir / charm / "src"),
            str(charms_dir / charm / "tests") if include_tests else "",
        )
        if file
    ]
    return files


###############################################
# Cli Definitions
###############################################
def _add_charm_argument(parser: argparse.ArgumentParser):
    parser.add_argument("charm", type=str, nargs="*", help="The charm to operate on.")


def main_cli():
    """Run the main CLI tool."""
    main_parser = argparse.ArgumentParser(description="Slurm Charms Repository utilities.")
    main_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging."
    )
    subparsers = main_parser.add_subparsers(required=True, help="sub-command help")

    stage_parser = subparsers.add_parser("stage", help="Stage charm(s).")
    _add_charm_argument(stage_parser)
    stage_parser.add_argument(
        "--clean",
        action="store_true",
        default=False,
        help="Clean the charm(s) first.",
    )
    stage_parser.add_argument("--dry-run", action="store_true", default=False, help="Dry run.")
    stage_parser.set_defaults(func=stage_cli)

    gen_token_parser = subparsers.add_parser("generate-token", help="Generate Charmhub token to publish charms.")
    gen_token_parser.set_defaults(func=gen_token_cli)

    clean_parser = subparsers.add_parser("clean", help="Clean charm(s).")
    _add_charm_argument(clean_parser)
    clean_parser.add_argument("--dry-run", action="store_true", default=False, help="Dry run.")
    clean_parser.set_defaults(func=clean_cli)

    validate_parser = subparsers.add_parser("validate", help="Validate charm(s).")
    _add_charm_argument(validate_parser)
    validate_parser.set_defaults(func=validate_cli)

    pythonpath_parser = subparsers.add_parser("pythonpath", help="Print the pythonpath.")
    pythonpath_parser.set_defaults(func=pythonpath_cli)

    fetch_lib_parser = subparsers.add_parser("fetch-lib", help="Fetch the external libraries.")
    fetch_lib_parser.add_argument("libraries", type=str, nargs="*", help="Libraries to fetch.")
    fetch_lib_parser.set_defaults(func=fetch_lib_cli)

    fmt_parser = subparsers.add_parser("fmt", help="Apply formatting standards to code.")
    fmt_parser.set_defaults(func=fmt_cli)

    lint_parser = subparsers.add_parser("lint", help="Check code against coding style standards")
    lint_parser.add_argument(
        "--fix", action="store_true", default=False, help="Try to fix the lint err ors"
    )
    lint_parser.set_defaults(func=lint_cli)

    type_parser = subparsers.add_parser("type", help="Type checking with pyright.")
    _add_charm_argument(type_parser)
    type_parser.set_defaults(func=type_cli)

    unit_test_parser = subparsers.add_parser("unit", help="Run unit tests.")
    _add_charm_argument(unit_test_parser)
    unit_test_parser.set_defaults(func=unit_test_cli)

    build_parser = subparsers.add_parser("build", help="Build all the specified slurm charms.")
    _add_charm_argument(build_parser)
    build_parser.set_defaults(func=build_cli)

    integration_test_parser = subparsers.add_parser("integration", help="Run integration tests.")
    integration_test_parser.add_argument(
        "rest", type=str, nargs="*", help="Arguments forwarded to pytest"
    )
    _add_charm_argument(integration_test_parser)
    integration_test_parser.set_defaults(func=integration_tests_cli)

    args = main_parser.parse_args()
    level = logging.INFO
    if args.verbose:
        level = logging.DEBUG
    logger.setLevel(level)
    context = vars(args)
    context["internal_libraries"] = load_internal_libraries()
    context["external_libraries"] = load_external_libraries()
    context["templates"] = load_templates()
    context["slurm_charms"] = list_charms()
    if "charm" in context:
        charms = context.pop("charm")
        if not charms:
            charms = context["slurm_charms"]
        context["charms"] = [
            validate_charm(
                charm,
                context["internal_libraries"],
                context["external_libraries"],
                context["templates"],
            )
            for charm in charms
        ]
    args.func(**context)


def stage_cli(
    charms: list[SlurmCharm],
    internal_libraries: dict[str, pathlib.Path],
    external_libraries: dict[str, pathlib.Path],
    templates: dict[str, pathlib.Path],
    clean: bool = False,
    dry_run: bool = False,
    **kwargs,
):
    """Stage the specified charms into the build directory."""
    for charm in charms:
        logger.info("Preparing the charm %s", charm.path.name)
        if clean:
            clean_charm(charm, dry_run=dry_run)
        stage_charm(
            charm,
            internal_libraries,
            external_libraries,
            templates,
            dry_run=dry_run,
        )

def gen_token_cli(
    slurm_charms: [str],
    **kwargs,
):
    """Generate Charmhub token to publish charms."""
    args = [
        "charmcraft",
        "login",
        "--export=.charmhub.secret"
    ] + [f"--charm={charm}" for charm in slurm_charms] + [
        "--permission=package-manage-metadata",
        "--permission=package-manage-releases",
        "--permission=package-manage-revisions",
        "--permission=package-view-metadata",
        "--permission=package-view-releases",
        "--permission=package-view-revisions",
        "--ttl=7776000" # 90 days
    ]
    subprocess.run(args, check=True)

def clean_cli(
    charms: list[SlurmCharm],
    internal_libraries: dict[str, pathlib.Path],
    external_libraries: dict[str, pathlib.Path],
    templates: dict[str, pathlib.Path],
    dry_run: bool = False,
    **kwargs,
):
    """Clean all the build artifacts for the specified charms."""
    for charm in charms:
        logger.info("Cleaning the charm %s", charm.path.name)
        clean_charm(charm, dry_run=dry_run)
    if not dry_run:
        try:
            BUILD_PATH.rmdir()
            logger.info(f"Deleted empty build directory {BUILD_PATH}")
        except OSError as e:
            # ENOENT   (2)  - No such file or directory
            # ENOEMPTY (39) - Directory not empty
            if e.errno != 39 and e.errno != 2:
                raise e


def validate_cli(
    charms: list[SlurmCharm],
    internal_libraries: dict[str, pathlib.Path],
    external_libraries: dict[str, pathlib.Path],
    templates: dict[str, pathlib.Path],
    **kwargs,
):
    """Validate all the specified charms.

    Currently a no op because this is done in the main_cli.
    """
    for charm in charms:
        logging.info("Charm %s is valid.", charm.path.name)


def pythonpath_cli(internal_libraries: dict[str, pathlib.Path], **kwargs):
    """Print the pythonpath."""
    parent_dirs = set()
    for path in internal_libraries.values():
        parent_dirs.add(path.parents[3])
    parent_dirs.add(EXTERNAL_LIB_DIR)
    print(":".join(str(p) for p in parent_dirs))


def fetch_lib_cli(libraries: list[str], external_libraries: dict[str, pathlib.Path], **kwargs):
    """Fetch the external libraries."""
    cwd = EXTERNAL_LIB_DIR.parent
    libraries_set = set(libraries)
    if not libraries_set:
        libraries_set = set(external_libraries.keys())
    for library in libraries_set:
        logging.info(f"Fetching {library}")
        # Fetch the library
        subprocess.run(["charmcraft", "fetch-lib", library], cwd=cwd, check=True)


def fmt_cli(
    slurm_charms: [str],
    **kwargs,
):
    """Apply formatting standards to code. """
    files = get_source_dirs(slurm_charms)
    logging.info(f"Running black for directories {files}")
    subprocess.run(["black", "--config", "pyproject.toml"] + files, cwd=ROOT_DIR, check=True)


def lint_cli(
    slurm_charms: [str],
    fix: bool,
    **kwargs,
):
    """Check code against coding style standards."""
    files = get_source_dirs(slurm_charms)
    logging.info("Target directories: {files}")
    if fix:
        logging.info("Trying to automatically fix the lint errors.")
    logging.info("Running black...")
    subprocess.run(
        ["black", "--config", "pyproject.toml"] + ([] if fix else ["--check"]) + files,
        cwd=ROOT_DIR,
        check=True,
    )
    logging.info("Running codespell...")
    subprocess.run(["codespell"] + (["-w"] if fix else []) + files, cwd=ROOT_DIR, check=True)
    logging.info("Running ruff...")
    subprocess.run(
        ["ruff", "check"] + (["--fix"] if fix else []) + files, cwd=ROOT_DIR, check=True
    )


def type_cli(
    charms: [SlurmCharm],
    internal_libraries: dict[str, pathlib.Path],
    external_libraries: dict[str, pathlib.Path],
    templates: dict[str, pathlib.Path],
    **kwargs,
):
    """Type checking with pyright."""
    for charm in charms:
        logger.info("Staging the charm %s", charm.path.name)
        stage_charm(
            charm,
            internal_libraries,
            external_libraries,
            templates,
            dry_run=False,
        )
        logger.info("Running pyright...")
        subprocess.run(
            ["pyright", "./src"],
            cwd=charm.build_path,
            check=True,
            env={**os.environ, "PYTHONPATH": f"{charm.build_path}/src:{charm.build_path}/lib"},
        )


def unit_test_cli(
    charms: [SlurmCharm],
    internal_libraries: dict[str, pathlib.Path],
    external_libraries: dict[str, pathlib.Path],
    templates: dict[str, pathlib.Path],
    **kwargs,
):
    """Run unit tests."""
    subprocess.run(["coverage", "erase"], check=True)

    files = []

    for charm in charms:
        logger.info("Staging the charm %s", charm.path.name)
        stage_charm(
            charm,
            internal_libraries,
            external_libraries,
            templates,
            dry_run=False,
        )
        logger.info("Running unit tests for %s", charm.path.name)
        subprocess.run(["coverage", "erase"], cwd=charm.build_path, check=True)
        subprocess.run(
            "coverage run --source ./src -m pytest -v --tb native -s ./tests/unit".split(),
            cwd=charm.build_path,
            check=True,
            env={**os.environ, "PYTHONPATH": f"{charm.build_path}/src:{charm.build_path}/lib"},
        )
        cov_path = charm.build_path / ".coverage"
        if cov_path.is_file():
            files.append(str(cov_path))

    logger.info("Generating global results...")
    subprocess.run(["coverage", "combine"] + files, check=True)
    subprocess.run(["coverage", "report"], check=True)
    logger.info(f"File generated at {ROOT_DIR}/.coverage")


def build_cli(
    charms: [SlurmCharm],
    internal_libraries: dict[str, pathlib.Path],
    external_libraries: dict[str, pathlib.Path],
    templates: dict[str, pathlib.Path],
    **kwargs,
):
    """Build all the specified slurm charms."""
    for charm in charms:
        logger.info("Staging the charm %s", charm.path.name)
        stage_charm(
            charm,
            internal_libraries,
            external_libraries,
            templates,
            dry_run=False,
        )
        logger.info("Building the charm %s", charm.path.name)
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
    charms: [SlurmCharm],
    internal_libraries: dict[str, pathlib.Path],
    external_libraries: dict[str, pathlib.Path],
    templates: dict[str, pathlib.Path],
    rest: [str],
    **kwargs,
):
    """Run integration tests."""
    local_charms = {}

    for charm in charms:
        stage_charm(charm, internal_libraries, external_libraries, templates)
        local_charms[f"{charm.path.name.upper()}_DIR"] = charm.build_path

    subprocess.run(
        "pytest -v -s --tb native --log-cli-level=INFO ./tests/integration".split() + rest,
        check=True,
        env={**os.environ, **local_charms},
    )


if __name__ == "__main__":
    main_cli()
