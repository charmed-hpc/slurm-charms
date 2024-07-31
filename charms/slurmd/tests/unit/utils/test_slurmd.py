#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
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

"""Unit tests for the slurmd utility module."""

import datetime
import subprocess
import unittest
from unittest.mock import Mock, patch

from utils import slurmd


class TestSlurmd(unittest.TestCase):
    """Unit tests for methods in slurmd utility module."""

    @patch("charms.operator_libs_linux.v1.systemd._systemctl")
    def test_start(self, _) -> None:
        slurmd.start()

    @patch("charms.operator_libs_linux.v1.systemd._systemctl")
    def test_stop(self, _) -> None:
        slurmd.stop()

    @patch("charms.operator_libs_linux.v1.systemd._systemctl")
    def test_restart(self, _) -> None:
        slurmd.restart()

    @patch("pathlib.Path.write_text")
    def test_overwrite_default(self, _) -> None:
        slurmd.override_default("127.0.0.1")

    @patch("pathlib.Path.is_dir", return_value=False)
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.write_text")
    @patch("charms.operator_libs_linux.v1.systemd._systemctl")
    def test_override_service_no_service_d(self, *_) -> None:
        """Test override_service(...) when slurmd.service.d does not exist."""
        slurmd.override_service()

    @patch("pathlib.Path.is_dir", return_value=True)
    @patch("pathlib.Path.write_text")
    @patch("charms.operator_libs_linux.v1.systemd._systemctl")
    def test_override_service_yes_service_d(self, *_) -> None:
        """Test override_service(...) when slurmd.service.d exists."""
        slurmd.override_service()

    @patch("datetime.timedelta", return_value=datetime.timedelta(-1))
    def test_start_slurmd_service_fail(self, _) -> None:
        """Test _start_slurmd_service() as if slurmd fails to start.

        Notes:
            This method forces the slurmd wrapper to exit because it sets
            the end_time to yesterday instead of the future.
        """
        with self.assertRaises(SystemExit) as e:
            slurmd._start_slurmd_service()

        self.assertEqual(e.exception.code, 1)

    @patch("subprocess.Popen")
    def test_start_slurmd_service_success(self, mock_popen) -> None:
        """Test _start_slurmd_service() as if slurmd succeeds to start."""
        process_mock = Mock()
        process_mock.configure_mock(**{"wait.side_effect": subprocess.TimeoutExpired("", 0)})
        mock_popen.return_value = process_mock
        slurmd._start_slurmd_service()
