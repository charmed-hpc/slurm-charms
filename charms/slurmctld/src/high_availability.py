# Copyright 2025-2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Slurmctld high availability (HA) features."""

import logging
import shutil
from datetime import datetime
from pathlib import Path
from subprocess import CalledProcessError

import ops
from charmed_hpc_libs.ops import call
from charms.filesystem_client.v0.mount_info import (
    MountedFilesystemEvent,
    MountInfo,
    MountProviderConnectedEvent,
    MountRequires,
)
from constants import HA_MOUNT_LOCATION

_logger = logging.getLogger(__name__)


class SlurmctldHA(ops.Object):
    """Slurmctld high availability (HA)."""

    def __init__(self, charm, relation_name: str):
        """Initialize filesystem-client event observation."""
        super().__init__(charm, relation_name)
        self._charm = charm
        self._mount = MountRequires(self._charm, relation_name)

        self.framework.observe(
            self._mount.on.mount_provider_connected, self._on_mount_provider_connected
        )
        self.framework.observe(self._mount.on.mounted_filesystem, self._on_mounted_filesystem)

    def _on_mount_provider_connected(self, event: MountProviderConnectedEvent) -> None:
        """Handle filesystem-client connected event."""
        for relation in self._mount.relations:
            self._mount.set_mount_info(relation.id, MountInfo(mountpoint=HA_MOUNT_LOCATION))
        status_message = f"Requesting file system mount: {HA_MOUNT_LOCATION}"
        _logger.debug(status_message)
        self._charm.unit.status = ops.MaintenanceStatus(status_message)

    def _on_mounted_filesystem(self, event: MountedFilesystemEvent) -> None:
        """Handle filesystem-client mounted event."""
        if self._charm.unit.is_leader() and not self._charm.slurmctld.config.path.exists():
            _logger.debug("slurm.conf not found. deferring event")
            event.defer()
            return

        # Both leader and non-leaders migrate /etc/ config files
        # Leader copies its config files and non-leaders symlink to that copy
        etc_source = Path("/etc/slurm")
        target = Path(HA_MOUNT_LOCATION)

        try:
            self._migrate_etc_data(etc_source, target / "etc" / "slurm")
        except shutil.Error:
            _logger.exception("failed to migrate %s to %s. deferring event", etc_source, target)
            event.defer()
            return

        if not self._charm.unit.is_leader():
            # Non-leaders have no more data to migrate
            _logger.debug("storage mounted. starting unit")
            self._charm.on.start.emit()
            return

        # The leader must also migrate StateSaveLocation data
        config = self._charm.slurmctld.config.load()
        state_save_source = Path(config.state_save_location)

        try:
            self._migrate_state_save_location_data(state_save_source, target)
        except CalledProcessError:
            _logger.exception(
                "failed to migrate %s to %s. deferring event", state_save_source, target
            )
            event.defer()
            return

        # Migration has been successful, update configs to the new path and restart service
        new_state_save_location = target / state_save_source.name
        with self._charm.slurmctld.config.edit() as config:
            config.state_save_location = str(new_state_save_location)
        _logger.debug("state save location updated to %s", new_state_save_location)
        self._charm.on.start.emit()

    def _migrate_etc_data(self, source: Path, target: Path) -> None:
        """Migrate the given source etc directory to the given target.

        The charm leader recursively copies the source directory to the target.
        All units then replace the source with a symlink to the target.

        This is necessary in a high availability (HA) deployment as all slurmctld units require
        access to identical conf files. For this reason, the target must be located on shared
        storage mounted on all slurmctld units.

        To avoid data loss, the existing configuration is backed up to a directory suffixed by the
        current date and time before migration. For example, `/etc/slurm_20250620_161437`.

        Args:
            source: Path to the directory containing Slurm config files, such as `/etc/slurm`
            target: Path to the directory Slurm config files are migrated to,
                    such as `HA_MOUNT_LOCATION`
        """
        # Nothing to do if target already correctly symlinked
        if source.is_symlink() and source.resolve() == target:
            _logger.debug("%s -> %s sylink already exists", source, target)
            return

        if source.exists():
            if self._charm.unit.is_leader():
                if not target.exists():
                    _logger.debug("leader copying %s to %s", source, target)

                    def copy_preserve_ids(source, target):
                        """Preserve owner and group IDs of copied files."""
                        output = shutil.copy2(source, target)
                        stat = Path(source).stat()
                        shutil.chown(target, user=stat.st_uid, group=stat.st_gid)
                        return output

                    shutil.copytree(
                        source, target, copy_function=copy_preserve_ids, dirs_exist_ok=True
                    )
                else:
                    _logger.warning("%s already exists. aborting copy from %s", target, source)

            # Timestamp to avoid overwriting any existing backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_target = Path(f"{source}_{timestamp}")
            _logger.debug("backing up %s to %s", source, backup_target)
            shutil.move(source, backup_target)
        else:
            _logger.warning("%s not found. unable to backup existing slurm data", source)

        _logger.debug("symlinking %s to %s", source, target)
        source.symlink_to(target)

    def _migrate_state_save_location_data(self, source: Path, target: Path):
        """Migrate the given source StateSaveLocation directory to the given target.

        Performs an initial `rsync` to the target while slurmctld.service is running.
        Then stops the service and runs a second `rsync` to copy the delta.

        Args:
            source: Path to the directory containing StateSaveLocation data,
                    such as `/var/lib/slurm/checkpoint`
            target: Path to the *parent* directory the source is migrated to,
                    such as `HA_MOUNT_LOCATION` to migrate to `HA_MOUNT_LOCATION/checkpoint`

        Notes:
            On the success of this function, the slurmctld service remains stopped to allow for the
            caller to appropriately update `slurm.conf`. Once `slurm.conf` is updated, the caller
            *must* restart the slurmctld.service.
        """
        checkpoint_target = target / source.name
        if checkpoint_target.exists():
            _logger.warning("%s already exists. aborting copy from %s", checkpoint_target, source)
            return

        status_message = f"Migrating {source} to {target}"
        _logger.debug(status_message)
        self._charm.unit.status = ops.MaintenanceStatus(status_message)

        # Perform initial copy of data while slurmctld.service is still running then stop and sync
        # the delta
        rsync = "/usr/bin/rsync"
        rsync_args = ["--archive", "--delete", str(source), str(target)]
        try:
            call(rsync, *rsync_args)
        except CalledProcessError:
            _logger.exception("failed initial sync of %s to %s", source, target)
            raise

        self._charm.slurmctld.service.stop()

        try:
            call(rsync, *rsync_args)
        except CalledProcessError:
            _logger.exception("failed delta sync of %s to %s", source, target)
            # Immediately restart slurmctld.service on failure
            self._charm.slurmctld.service.start()
            raise

        # On success, slurmctld.service remains stopped and must be restarted by the function caller
