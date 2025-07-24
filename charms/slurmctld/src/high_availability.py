# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Slurmctld high availability (HA) features."""

import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from constants import HA_MOUNT_POINT
from ops import (
    MaintenanceStatus,
    Object,
)

from charms.filesystem_client.v0.mount_info import (
    MountedFilesystemEvent,
    MountInfo,
    MountProviderConnectedEvent,
    MountRequires,
)

logger = logging.getLogger()


class SlurmctldHA(Object):
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
            self._mount.set_mount_info(relation.id, MountInfo(mountpoint=HA_MOUNT_POINT))
        status_message = f"requesting file system mount: {HA_MOUNT_POINT}"
        logger.debug(status_message)
        self._charm.unit.status = MaintenanceStatus(status_message)

    def _on_mounted_filesystem(self, event: MountedFilesystemEvent) -> None:
        """Handle filesystem-client mounted event."""
        checkpoint_data = self._charm._slurmctld_peer.checkpoint_data
        if checkpoint_data is None:
            logger.debug("checkpoint data not set. deferring event")
            event.defer()
            return

        # Both /etc config files and StateSaveLocation data are to be migrated
        etc_source = Path("/etc/slurm")
        state_save_source = Path(checkpoint_data["StateSaveLocation"])
        target = Path(HA_MOUNT_POINT)

        try:
            self._migrate_etc_data(etc_source, target / "etc" / "slurm")
        except shutil.Error:
            logger.exception("failed to migrate %s to %s. deferring event", etc_source, target)
            event.defer()
            return

        if not self._charm.unit.is_leader():
            # Non-leaders do not have any more data to migrate
            logger.debug("storage mounted. starting unit")
            self._charm.on.start.emit()
            return

        # JWT key requires separate handling - it may be in the state directory
        jwt_key_path = Path(checkpoint_data["AuthAltParameters"]["jwt_key"])
        if jwt_key_path.is_relative_to(state_save_source):
            # Given:
            #
            # jwt_key_path      = /var/lib/slurm/checkpoint/jwt_hs256.key
            # state_save_source = /var/lib/slurm/checkpoint
            # target            = /mnt/slurmctld-statefs
            #
            # jwt_key_path becomes /mnt/slurmctld-statefs/checkpoint/jwt_hs256.key
            jwt_key_path = target / jwt_key_path.relative_to(state_save_source.parent)
            checkpoint_data["AuthAltParameters"]["jwt_key"] = str(jwt_key_path)

        checkpoint_data["StateSaveLocation"] = str(target / state_save_source.name)

        try:
            self._migrate_state_save_location_data(state_save_source, target)
        except subprocess.CalledProcessError:
            logger.exception(
                "failed to migrate %s to %s. deferring event", state_save_source, target
            )
            event.defer()
            return

        # Update configs to the new path only if sync was successful
        self._charm.set_jwt_path(jwt_key_path)
        self._charm._slurmctld_peer.checkpoint_data = checkpoint_data
        self._charm._on_write_slurm_conf(event)
        self._charm._check_status()

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
            source: Path to the directory containing Slurm config files, e.g. `/etc/slurm`
            target: Path to the directory Slurm config files are migrated to,
                    e.g. `/mnt/slurmctld-statefs`
        """
        # Nothing to do if target already correctly symlinked
        if source.is_symlink() and source.resolve() == target:
            logger.debug("%s -> %s sylink already exists", source, target)
            return

        if source.exists():
            if self._charm.unit.is_leader():
                logger.debug("leader copying %s to %s", source, target)

                def copy_preserve_ids(source, target):
                    """Preserve owner and group IDs of copied files."""
                    output = shutil.copy2(source, target)
                    stat = Path(source).stat()
                    shutil.chown(target, user=stat.st_uid, group=stat.st_gid)
                    return output

                shutil.copytree(
                    source, target, copy_function=copy_preserve_ids, dirs_exist_ok=True
                )

            # Timestamp to avoid overwriting any existing backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_target = Path(f"{source}_{timestamp}")
            logger.debug("backing up %s to %s", source, backup_target)
            shutil.move(source, backup_target)
        else:
            logger.warning("%s not found. unable to backup existing slurm data", source)

        logger.debug("symlinking %s to %s", source, target)
        source.symlink_to(target)

    def _migrate_state_save_location_data(self, source: Path, target: Path):
        """Migrate the given source StateSaveLocation directory to the given target.

        Performs an initial `rsync` to the target while slurmctld.service is running.
        Then stops the service and runs a second `rsync` to copy the delta.

        Args:
            source: Path to the directory containing StateSaveLocation data,
                    e.g. `/var/lib/slurm/checkpoint`
            target: Path to the *parent* directory the source is migrated to,
                    e.g. `/mnt/slurmctld-statefs` to migrate to `/mnt/slurmctld-statefs/checkpoint`
        """
        checkpoint_target = target / source.name
        if checkpoint_target.exists() and source == checkpoint_target:
            logger.warning(
                "state save location is already %s. aborting migration", checkpoint_target
            )
            return

        status_message = f"migrating {source} to {target}"
        logger.debug(status_message)
        self._charm.unit.status = MaintenanceStatus(status_message)

        # Perform initial copy of data while slurmctld.service is still running then stop and sync
        # the delta
        rsync_cmd = f"/usr/bin/rsync --archive --delete {source} {target}".split()
        try:
            subprocess.check_output(rsync_cmd)
        except subprocess.CalledProcessError:
            logger.exception("failed initial sync of %s to %s", source, target)
            raise

        self._charm._slurmctld.service.stop()

        try:
            subprocess.check_output(rsync_cmd)
        except subprocess.CalledProcessError:
            logger.exception("failed delta sync of %s to %s", source, target)
            self._charm._slurmctld.service.start()
            raise

        # slurmctld.service is restarted by _on_write_slurm_conf() call after this function
