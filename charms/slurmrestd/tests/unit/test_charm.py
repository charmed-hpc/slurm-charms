#!/usr/bin/env python3
# Copyright 2023-2025 Canonical Ltd.
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

"""Unit tests for the `slurmrestd` charm."""

import json
from pathlib import Path

import ops
import pytest
from charmed_slurm_slurmctld_interface import AUTH_KEY_LABEL
from constants import SLURMRESTD_INTEGRATION_NAME
from ops import testing
from pytest_mock import MockerFixture

EXAMPLE_AUTH_KEY = "xyz123=="
EXAMPLE_AUTH_KEY_ID = "12345678-90ab-cdef-1234-567890abcdef"
EXAMPLE_CONTROLLERS = ["juju-988225-0:6817", "juju-988225-1:6817"]


@pytest.fixture
def auth_key_secret() -> testing.Secret:
    """Mock Slurm auth key secret."""
    return testing.Secret(
        label=AUTH_KEY_LABEL,
        tracked_content={"key": EXAMPLE_AUTH_KEY, "keyid": EXAMPLE_AUTH_KEY_ID},
    )


@pytest.mark.parametrize(
    "leader",
    (
        pytest.param(True, id="leader"),
        pytest.param(False, id="not leader"),
    ),
)
class TestSlurmrestdCharm:
    """Unit tests for the `slurmrestd` charmed operator."""

    def test_on_secret_changed_success(
        self, mock_charm, mocker: MockerFixture, leader, auth_key_secret
    ) -> None:
        """Test successful execution of the `_on_secret_changed` event handler."""
        key_file_path = Path("/etc/slurm/slurm.jwks")
        expected_key_file_content = {
            "keys": [
                {"alg": "HS256", "kty": "oct", "kid": EXAMPLE_AUTH_KEY_ID, "k": EXAMPLE_AUTH_KEY}
            ]
        }

        integration_id = 1
        integration = testing.Relation(
            endpoint=SLURMRESTD_INTEGRATION_NAME,
            interface="slurmrestd",
            id=integration_id,
            remote_app_name="slurmctld",
            remote_app_data={
                "auth_key": '"***"',
                "auth_key_id": json.dumps(auth_key_secret.id),
                "controllers": json.dumps(EXAMPLE_CONTROLLERS),
            },
        )

        with mock_charm(
            mock_charm.on.secret_changed(auth_key_secret),
            testing.State(leader=leader, relations={integration}, secrets={auth_key_secret}),
        ) as manager:
            slurmrestd = manager.charm.slurmrestd
            mocker.patch.object(slurmrestd, "is_installed", return_value=True)
            mocker.patch.object(slurmrestd.service, "is_active")
            mocker.patch("shutil.chown")  # User/group `slurm` doesn't exist on host.

            state = manager.run()

        assert key_file_path.exists(), f"File {key_file_path} does not exist"
        key_file_text = key_file_path.read_text()
        actual_key_file_content = json.loads(key_file_text)
        assert actual_key_file_content == expected_key_file_content
        assert state.unit_status == ops.ActiveStatus()

    def test_on_secret_changed_empty_key_id_failure(
        self, mock_charm, mocker: MockerFixture, leader
    ) -> None:
        """Test `_on_secret_changed` event handler when auth key ID is empty."""
        auth_key_secret = testing.Secret(
            label=AUTH_KEY_LABEL, tracked_content={"key": EXAMPLE_AUTH_KEY, "keyid": ""}
        )
        integration_id = 1
        integration = testing.Relation(
            endpoint=SLURMRESTD_INTEGRATION_NAME,
            interface="slurmrestd",
            id=integration_id,
            remote_app_name="slurmctld",
            remote_app_data={
                "auth_key": '"***"',
                "auth_key_id": json.dumps(auth_key_secret.id),
                "controllers": json.dumps(EXAMPLE_CONTROLLERS),
            },
        )

        with mock_charm(
            mock_charm.on.secret_changed(auth_key_secret),
            testing.State(leader=leader, relations={integration}, secrets={auth_key_secret}),
        ) as manager:
            slurmrestd = manager.charm.slurmrestd
            mocker.patch.object(slurmrestd, "is_installed", return_value=True)

            state = manager.run()

        assert state.unit_status == ops.BlockedStatus(
            "Failed to retrieve Slurm authentication key. See `juju debug-log` for details"
        )
