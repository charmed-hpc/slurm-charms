#!/usr/bin/env python3
# Copyright 2023-2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for the `slurmctld` charmed operator."""

import textwrap
from pathlib import Path

import pytest
from charmed_slurm_oci_runtime_interface import OCIRuntimeDisconnectedEvent, OCIRuntimeReadyEvent
from charmlibs import apt
from constants import (
    CLUSTER_NAME_PREFIX,
    MAIL_INTEGRATION_NAME,
    OCI_RUNTIME_INTEGRATION_NAME,
    PEER_INTEGRATION_NAME,
)
from ops import testing
from pytest_mock import MockerFixture
from slurm_ops import SlurmOpsError
from slurmutils import OCIConfig

EXAMPLE_OCI_CONFIG = OCIConfig(
    ignorefileconfigjson=False,
    envexclude="^(SLURM_CONF|SLURM_CONF_SERVER)=",
    runtimeenvexclude="^(SLURM_CONF|SLURM_CONF_SERVER)=",
    runtimerun="apptainer exec --userns %r %@",
    runtimekill="kill -s SIGTERM %p",
    runtimedelete="kill -s SIGKILL %p",
)
EXAMPLE_KEY_ENTRY = {"keys": [{"alg": "HS256", "kty": "oct", "kid": "0", "k": "xyz123=="}]}


@pytest.fixture
def peer_integration():
    """Peer integration fixture."""
    return testing.PeerRelation(
        endpoint=PEER_INTEGRATION_NAME,
        interface="slurmctld-peer",
        local_app_data={"cluster_name": '"charmed-hpc"'},
    )


@pytest.fixture
def smtp_relation():
    """SMTP relation fixture."""
    return testing.Relation(
        endpoint=MAIL_INTEGRATION_NAME,
        interface="smtp",
        remote_app_name="smtp-integrator",
    )


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSlurmctldCharm:
    """Unit tests for the `slurmctld` charmed operator."""

    @pytest.mark.parametrize(
        "cluster_name",
        (
            pytest.param("polaris", id="cluster name configured"),
            pytest.param("", id="no cluster name configured"),
        ),
    )
    def test_on_slurmctld_peer_connected(
        self, mocker: MockerFixture, mock_charm, leader, cluster_name
    ) -> None:
        """Test the `_on_slurmctld_peer_connected` event handler."""
        # Patch `secrets.token_urlsafe(...)` to have predictable output.
        slug = "xyz1"
        mocker.patch("secrets.token_urlsafe", return_value=slug)

        peer_integration_id = 1
        peer_integration = testing.PeerRelation(
            endpoint=PEER_INTEGRATION_NAME,
            interface="slurmctld-peer",
            id=peer_integration_id,
        )

        state = mock_charm.run(
            mock_charm.on.relation_created(peer_integration),
            testing.State(
                leader=leader, relations={peer_integration}, config={"cluster-name": cluster_name}
            ),
        )

        integration = state.get_relation(peer_integration_id)
        if leader:
            assert "cluster_name" in integration.local_app_data
            if cluster_name:
                assert integration.local_app_data["cluster_name"] == '"polaris"'
            else:
                assert (
                    integration.local_app_data["cluster_name"] == f'"{CLUSTER_NAME_PREFIX}-{slug}"'
                )
        else:
            assert "cluster_name" not in integration.local_app_data

    @pytest.mark.parametrize(
        "ready",
        (
            pytest.param(True, id="ready"),
            pytest.param(False, id="not ready"),
        ),
    )
    def test_on_oci_runtime_ready(self, mock_charm, mocker: MockerFixture, ready, leader) -> None:
        """Test the `_on_oci_runtime_ready` event handler."""
        integration_id = 1
        integration = testing.Relation(
            endpoint=OCI_RUNTIME_INTEGRATION_NAME,
            interface="slurm-oci-runtime",
            id=integration_id,
            remote_app_name="apptainer",
            remote_app_data={"ociconfig": EXAMPLE_OCI_CONFIG.json()} if ready else {},
        )

        with mock_charm(
            mock_charm.on.relation_changed(integration),
            testing.State(leader=leader, relations={integration}),
        ) as manager:
            slurmctld = manager.charm.slurmctld
            mocker.patch.object(slurmctld, "is_installed", return_value=True)

            manager.run()

        if ready and leader:
            assert slurmctld.oci.path.exists()
            assert slurmctld.oci.load().dict() == EXAMPLE_OCI_CONFIG.dict()
        else:
            assert not slurmctld.oci.path.exists()
            # Assert that `OCIRuntimeReadyEvent` is never emitted on non-leader units or
            # on the leader unit if `remote_app_data` is empty.
            assert not any(
                isinstance(event, OCIRuntimeReadyEvent) for event in mock_charm.emitted_events
            )

    def test_on_oci_runtime_disconnected(self, mock_charm, mocker: MockerFixture, leader) -> None:
        """Test the `_on_oci_runtime_disconnected` event handler."""
        integration_id = 1
        integration = testing.Relation(
            endpoint=OCI_RUNTIME_INTEGRATION_NAME,
            interface="slurm-oci-runtime",
            id=integration_id,
            remote_app_name="apptainer",
        )

        with mock_charm(
            mock_charm.on.relation_broken(integration),
            testing.State(leader=leader, relations={integration}),
        ) as manager:
            slurmctld = manager.charm.slurmctld
            mocker.patch.object(slurmctld, "is_installed", return_value=True)

            manager.run()

        if leader:
            assert not slurmctld.oci.path.exists()
        else:
            # Assert that `OCIRuntimeDisconnectedEvent` is only handled by the `slurmctld` leader.
            assert not any(
                isinstance(event, OCIRuntimeDisconnectedEvent)
                for event in mock_charm.emitted_events
            )

    @pytest.mark.parametrize(
        "params,expected",
        (
            pytest.param(
                {"nodes": "slurmd-[0-19]", "state": "idle"},
                ("update", "nodename=slurmd-[0-19]", "state=idle"),
                id="idle",
            ),
            pytest.param(
                {"nodes": "slurmd-[20-24]", "state": "draining"},
                ("update", "nodename=slurmd-[20-24]", "state=draining", "reason='n/a'"),
                id="draining",
            ),
            pytest.param(
                {"nodes": "slurmd-[25-29]", "state": "down", "reason": "maintenance"},
                ("update", "nodename=slurmd-[25-29]", "state=down", "reason='maintenance'"),
                id="down",
            ),
        ),
    )
    def test_on_set_node_state_action(
        self, mock_charm, mock_scontrol, succeed, params, expected, leader
    ) -> None:
        """Test the `_on_set_node_state_action` action event handler."""
        if succeed:
            mock_charm.run(mock_charm.on.action("set-node-state", params=params), testing.State())
            mock_scontrol.assert_called_with(*expected)
        else:
            mock_scontrol.side_effect = [SlurmOpsError("scontrol failed")]
            with pytest.raises(testing.ActionFailed) as exec_info:
                mock_charm.run(
                    mock_charm.on.action("set-node-state", params=params), testing.State()
                )

            assert exec_info.value.message == (
                f"Failed to set state of node(s) {params['nodes']} to state '{params['state']}'. "
                f"reason:\nscontrol failed"
            )

    def test_on_smtp_relation_created_success(
        self, mock_charm, mocker: MockerFixture, leader, smtp_relation, peer_integration
    ) -> None:
        """Test successful integration on the SMTP interface."""
        mock_add_package = mocker.patch.object(apt, "add_package")

        with mock_charm(
            mock_charm.on.relation_created(smtp_relation),
            testing.State(leader=leader, relations={smtp_relation, peer_integration}),
        ) as manager:
            mocker.patch.object(manager.charm.slurmctld, "is_installed", return_value=True)
            mocker.patch.object(manager.charm.slurmctld.service, "is_active", return_value=True)
            mocker.patch.object(manager.charm.slurmdbd, "is_ready", return_value=True)
            mocker.patch.object(manager.charm.slurmctld.key, "get", return_value=EXAMPLE_KEY_ENTRY)
            state = manager.run()

        mock_add_package.assert_called_once_with("slurm-mail")
        assert state.unit_status == testing.ActiveStatus()

    def test_on_smtp_relation_created_package_install_failure(
        self, mock_charm, mocker: MockerFixture, leader, smtp_relation, peer_integration
    ) -> None:
        """Test integration on the SMTP interface when package installation fails."""
        mock_add_package = mocker.patch.object(apt, "add_package")
        mock_add_package.side_effect = apt.PackageError()

        with mock_charm(
            mock_charm.on.relation_created(smtp_relation),
            testing.State(leader=leader, relations={smtp_relation, peer_integration}),
        ) as manager:
            mocker.patch.object(manager.charm.slurmctld, "is_installed", return_value=True)
            mocker.patch.object(manager.charm.slurmctld.service, "is_active", return_value=True)
            mocker.patch.object(manager.charm.slurmdbd, "is_ready", return_value=True)
            mocker.patch.object(manager.charm.slurmctld.key, "get", return_value=EXAMPLE_KEY_ENTRY)
            state = manager.run()

        assert state.unit_status == testing.BlockedStatus(
            "Failed to install slurm-mail package. See `juju debug-log` for details"
        )

    def test_on_smtp_relation_broken_success(
        self, mock_charm, mocker: MockerFixture, leader, smtp_relation, peer_integration
    ) -> None:
        """Test successful removal of integration on the SMTP interface."""
        mock_remove_package = mocker.patch.object(apt, "remove_package")

        with mock_charm(
            mock_charm.on.relation_broken(smtp_relation),
            testing.State(leader=leader, relations={smtp_relation, peer_integration}),
        ) as manager:
            mocker.patch.object(manager.charm.slurmctld, "is_installed", return_value=True)
            mocker.patch.object(manager.charm.slurmctld.service, "is_active", return_value=True)
            mocker.patch.object(manager.charm.slurmdbd, "is_ready", return_value=True)
            mocker.patch.object(manager.charm.slurmctld.key, "get", return_value=EXAMPLE_KEY_ENTRY)
            state = manager.run()

        mock_remove_package.assert_called_once_with("slurm-mail")
        assert state.unit_status == testing.ActiveStatus()

    def test_on_smtp_relation_broken_failure(
        self, mock_charm, mocker: MockerFixture, leader, smtp_relation, peer_integration
    ) -> None:
        """Test integration on the SMTP interface when package removal fails."""
        mock_remove_package = mocker.patch.object(apt, "remove_package")
        mock_remove_package.side_effect = apt.PackageError()

        with mock_charm(
            mock_charm.on.relation_broken(smtp_relation),
            testing.State(leader=leader, relations={smtp_relation, peer_integration}),
        ) as manager:
            mocker.patch.object(manager.charm.slurmctld, "is_installed", return_value=True)
            mocker.patch.object(manager.charm.slurmctld.service, "is_active", return_value=True)
            mocker.patch.object(manager.charm.slurmdbd, "is_ready", return_value=True)
            mocker.patch.object(manager.charm.slurmctld.key, "get", return_value=EXAMPLE_KEY_ENTRY)
            state = manager.run()

        assert state.unit_status == testing.BlockedStatus(
            "Failed to uninstall slurm-mail package. See `juju debug-log` for details"
        )

    def test_on_smtp_data_available(
        self, mock_charm, mocker: MockerFixture, leader, peer_integration
    ) -> None:
        """Test update of SMTP data."""
        password = "password%1234"
        secret = testing.Secret({"password": password}, owner="app")
        smtp_data = {
            "user": "myuser",
            "password_id": secret.id,
            "host": "smtp.example.com",
            "port": "1025",
            "auth_type": "none",
            "transport_security": "starttls",
        }

        smtp_integration = testing.Relation(
            endpoint=MAIL_INTEGRATION_NAME,
            interface="smtp",
            remote_app_name="smtp-integrator",
            remote_app_data=smtp_data,
        )

        # Initial slurm-mail.conf
        # Includes parameters to remain unchanged to confirm only relevant lines are updated
        initial_config_content = textwrap.dedent("""
            [slurm-send-mail]
            logFile = /var/log/slurm-mail/slurm-send-mail.log
            emailFromName = Charmed HPC Admin
            smtpServer = localhost
            smtpPort = 25
            smtpUseTls = no
            smtpUseSsl = no
            smtpUserName =
            smtpPassword =
            tailExe = /usr/bin/tail
        """)
        expected_config_content = textwrap.dedent(f"""
            [slurm-send-mail]
            logFile = /var/log/slurm-mail/slurm-send-mail.log
            emailFromName = Charmed HPC Admin
            smtpServer = {smtp_data["host"]}
            smtpPort = {smtp_data["port"]}
            smtpUseTls = yes
            smtpUseSsl = no
            smtpUserName = {smtp_data["user"]}
            smtpPassword = {password}
            tailExe = /usr/bin/tail
        """)
        config_path = Path("/etc/slurm-mail/slurm-mail.conf")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(initial_config_content)

        with mock_charm(
            mock_charm.on.relation_changed(smtp_integration),
            testing.State(
                leader=leader, relations={smtp_integration, peer_integration}, secrets={secret}
            ),
        ) as manager:
            mocker.patch.object(manager.charm.slurmctld, "is_installed", return_value=True)
            mocker.patch.object(manager.charm.slurmctld.service, "is_active", return_value=True)
            mocker.patch.object(manager.charm.slurmdbd, "is_ready", return_value=True)
            mocker.patch.object(manager.charm.slurmctld.key, "get", return_value=EXAMPLE_KEY_ENTRY)
            state = manager.run()

        assert config_path.read_text().strip() == expected_config_content.strip()
        assert state.unit_status == testing.ActiveStatus()
