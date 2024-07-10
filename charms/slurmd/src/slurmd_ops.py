# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.
"""SlurmManager."""

import logging
import os
import shlex
import subprocess
import textwrap
from grp import getgrnam
from pathlib import Path
from pwd import getpwnam
from shutil import rmtree
from typing import Any, Dict

from constants import SLURM_GROUP, SLURM_SNAP, SLURM_USER

import charms.hpc_libs.v0.slurm_ops as slurm
import charms.operator_libs_linux.v1.systemd as systemd  # type: ignore [import-untyped]

logger = logging.getLogger()


TEMPLATE_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "templates"


def _get_slurm_user_uid_and_slurm_group_gid():
    """Return the slurm user uid and slurm group gid."""
    slurm_user_uid = getpwnam(SLURM_USER).pw_uid
    slurm_group_gid = getgrnam(SLURM_GROUP).gr_gid
    return slurm_user_uid, slurm_group_gid


class SlurmdException(BaseException):
    """SlurmdException."""

    def __init__(self, msg):
        pass


class SlurmdManager:
    """SlurmdManager."""

    def __init__(self):
        self._manager = slurm.SlurmManagerBase(slurm.ServiceType.SLURMD)

    def install(self) -> bool:
        """Install slurmd, slurm-client and munge packages to the system."""
        slurm.install()

        self._manager.disable()
        self._manager.munge.disable()

        os.symlink(
            "/etc/systemd/system/snap.slurm.slurmd.service", "/etc/systemd/system/slurm.service"
        )

        if not systemd.daemon_reload():
            return False

        if not self._install_nhc_from_tarball():
            logger.debug("Cannot install NHC")
            return False

        self.render_nhc_config()

        spool_dir = Path("/var/spool/slurmd")
        spool_dir.mkdir()

        return True

    def version(self) -> str:
        """Return slurm version."""
        return slurm.version()

    def write_munge_key(self, munge_key: str) -> None:
        """Base64 decode and write the munge key."""
        self._manager.munge.set_key(munge_key)

    def _install_nhc_from_tarball(self) -> bool:
        """Install NHC from tarball that is packaged with the charm.

        Returns True on success, False otherwise.
        """
        logger.info("#### Installing NHC")

        base_path = Path("/tmp/nhc")

        if base_path.exists():
            rmtree(base_path)
        base_path.mkdir()

        cmd = f"tar --extract --directory {base_path} --file lbnl-nhc-1.4.3.tar.gz".split()
        try:
            result = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            logger.debug(result)
        except subprocess.CalledProcessError as e:
            logger.error("failed to extract NHC using tar. reason:\n%s", e.stdout)
            return False

        full_path = base_path / os.listdir(base_path)[0]

        libdir = "/usr/lib"
        # NOTE: this requires make. We install it using the dispatch file in
        # the slurmd charm.
        try:
            locale = {"LC_ALL": "C", "LANG": "C.UTF-8"}
            cmd = f"./autogen.sh --prefix=/usr --sysconfdir=/etc \
                                 --libexecdir={libdir}".split()
            logger.info("##### NHC - running autogen")
            r = subprocess.run(
                cmd, cwd=full_path, env=locale, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            logger.debug(f"##### autogen: {r.stdout.decode()}")
            r.check_returncode()

            logger.info("##### NHC - running tests")
            r = subprocess.run(
                ["make", "test"],
                cwd=full_path,
                env=locale,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            logger.debug(f"##### NHC make test: {r.stdout.decode()}")
            r.check_returncode()
            if "tests passed" not in r.stdout.decode():
                logger.error("##### NHC tests failed")
                logger.error("##### Error installing NHC")
                return False

            logger.info("##### NHC - installing")
            r = subprocess.run(
                ["make", "install"],
                cwd=full_path,
                env=locale,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            logger.debug(f"##### NHC make install: {r.stdout.decode()}")
            r.check_returncode()
        except subprocess.CalledProcessError as e:
            logger.error(f"#### Error installing NHC: {e.cmd}")
            return False

        rmtree(base_path)
        logger.info("#### NHC successfully installed")
        return True

    def render_nhc_config(self, extra_configs=None) -> bool:
        """Render basic NHC.conf during installation.

        Returns True on success, False otherwise.
        """
        target = Path("/etc/nhc/nhc.conf")
        template = TEMPLATE_DIR / "nhc.conf.tmpl"

        try:
            target.write_text(template.read_text())
        except FileNotFoundError as e:
            logger.error(f"#### Error rendering NHC.conf: {e}")
            return False

        return True

    def render_nhc_wrapper(self, params: str) -> None:
        """Render the /usr/sbin/omni-nhc-wrapper script."""
        logger.debug(f"## rendering /usr/sbin/omni-nhc-wrapper: {params}")

        target = Path("/usr/sbin/omni-nhc-wrapper")

        target.write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash

                /usr/sbin/nhc-wrapper {params}
                """
            ).strip()
        )
        target.chmod(0o755)  # everybody can read/execute, owner can write

    def get_nhc_config(self) -> str:
        """Get current nhc.conf."""
        target = Path("/etc/nhc/nhc.conf")
        if target.exists():
            return target.read_text()
        return f"{target} not found."

    def restart_munged(self) -> bool:
        """Restart the munged process.

        Return True on success, and False otherwise.
        """
        try:
            logger.debug("## Restarting munge")
            self._manager.munge.enable()
            self._manager.munge.restart()
        except slurm.SlurmOpsError as e:  # type: ignore [misc]
            logger.error(e)
            return False
        return self.check_munged()

    def check_munged(self) -> bool:
        """Check if munge is working correctly."""
        if not systemd.service_running("snap.slurm.munged"):
            return False

        # check if munge is working, i.e., can use the credentials correctly
        try:
            logger.debug("## Testing if munge is working correctly")
            cmd = "slurm.munge -n"
            munge = subprocess.Popen(
                shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            unmunge = subprocess.Popen(
                ["slurm.unmunge"],
                stdin=munge.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if munge is not None:
                munge.stdout.close()  # type: ignore [union-attr]

            output = unmunge.communicate()[0].decode()
            if "Success" in output:
                logger.debug(f"## Munge working as expected: {output}")
                return True

            logger.error(f"## Munge not working: {output}")
        except subprocess.CalledProcessError as e:
            logger.error(f"## Error testing munge: {e}")

        return False

    def get_node_config(self) -> Dict[Any, Any]:
        """Return the node configuration options as reported by slurmd -C."""
        slurmd_config_options = ""
        try:
            slurmd_config_options = subprocess.check_output(
                [SLURM_SNAP / "sbin" / "slurmd", "-C"], text=True
            ).strip()
        except subprocess.CalledProcessError as e:
            logger.error(e)
            raise e

        slurmd_config_options_parsed = {str(): str()}
        try:
            slurmd_config_options_parsed = {
                item.split("=")[0]: item.split("=")[1]
                for item in slurmd_config_options.split()
                if item.split("=")[0] != "UpTime"
            }
        except IndexError as e:
            logger.error("Trouble accessing elements of the list.")
            raise e

        return slurmd_config_options_parsed

    def set_conf_server(self, server: str) -> None:
        """Set the config server that provides the config file.

        Args:
            server: Server hostname of the slurmctld service.
        """
        self._manager.config.set({"config-server": server})
