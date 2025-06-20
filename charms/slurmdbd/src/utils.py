#!/usr/bin/env python3
# Copyright (c) 2025 Vantage Compute Corporation
# See LICENSE file for licensing details.

"""utils.py."""
from typing import Dict
from urllib.parse import urlparse

from exceptions import InvalidDBURIError


def convert_db_uri_to_dict(db_uri: str) -> Dict[str, str]:
    """Convert db_uri to a dictionary of database connection parameters."""
    parsed = urlparse(db_uri)

    missing = []
    if not parsed.username:
        missing.append("username")
    if not parsed.password:
        missing.append("password")
    if not parsed.hostname:
        missing.append("hostname")
    if not parsed.port:
        missing.append("port")
    if not parsed.path or parsed.path == "/":
        missing.append("database (path)")

    if missing:
        raise InvalidDBURIError(f"Missing required component(s) in db-uri: {', '.join(missing)}")

    if parsed.scheme != "mysql":
        raise InvalidDBURIError(
            f"Invalid scheme: {parsed.scheme}. Only mysql scheme is supported."
        )

    return {
        "StorageUser": str(parsed.username),
        "StoragePass": str(parsed.password),
        "StorageHost": str(parsed.hostname),
        "StoragePort": str(parsed.port),
        "StorageLoc": parsed.path.lstrip("/"),
    }
