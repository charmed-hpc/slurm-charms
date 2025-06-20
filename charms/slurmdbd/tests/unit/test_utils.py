#!/usr/bin/env python3
# Copyright (c) 2025 Vantage Compute Corporation
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

"""Test functions in utils.py."""

# test_utils.py

import pytest
from exceptions import InvalidDBURIError
from utils import convert_db_uri_to_dict


def test_convert_db_uri_to_dict_raises_on_missing_components():
    malformed_uris = [
        "mysql://@host:3306/db",  # Missing user & pass
        "mysql://user@host/db",  # Missing password, port
        "mysql://user:pass@:3306/db",  # Missing host
        "mysql://user:pass@host/db",  # Missing port
        "mysql://user:pass@host:3306/",  # Missing db path
        "user:pass@host:3306/db",  # Missing schema
        "postgresql://user:pass@host:3306/db",  # Wrong schema
    ]

    for uri in malformed_uris:
        with pytest.raises(InvalidDBURIError):
            convert_db_uri_to_dict(uri)


def test_convert_db_uri_to_dict_mysql():
    uri = "mysql://user:pass@hostname:3306/database"
    expected = {
        "StorageUser": "user",
        "StoragePass": "pass",
        "StorageHost": "hostname",
        "StoragePort": "3306",
        "StorageLoc": "database",
    }
    result = convert_db_uri_to_dict(uri)
    assert result == expected


def test_convert_db_uri_to_dict_handles_path_slash():
    uri = "mysql://user:pass@host:3306//data/dir"
    expected = {
        "StorageUser": "user",
        "StoragePass": "pass",
        "StorageHost": "host",
        "StoragePort": "3306",
        "StorageLoc": "/data/dir".lstrip("/"),  # Ensures leading slash is removed
    }
    result = convert_db_uri_to_dict(uri)
    assert result == expected
