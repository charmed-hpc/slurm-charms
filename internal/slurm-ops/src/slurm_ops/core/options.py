# Copyright 2025 Canonical Ltd.
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

"""Utility functions for parsing and marshaling `<SERVICE>_OPTIONS` environment variables."""

__all__ = ["marshal_options", "parse_options"]

import shlex
from collections.abc import Mapping
from typing import Any


def marshal_options(options: Mapping[str, Any]) -> str:
    """Marshal a dictionary into a `<SERVICE>_OPTIONS` environment variable string value.

    Examples:
        >>> marshal_options(
        ...     {
        ...         '-Z': True,
        ...         '--conf': 'RealMemory=60000 CPUs=16',
        ...         '--conf-server': 'localhost:6817'
        ...     }
        ... )
        "-Z --conf 'RealMemory=60000 CPUs=16' --conf-server localhost:6817"
    """
    result: list[str] = []

    for k, v in options.items():
        if isinstance(v, bool):
            if v:
                result.append(k)
        else:
            result.extend((k, v))

    return shlex.join(result)


def parse_options(options: str) -> dict[str, Any]:
    """Parse the `<SERVICE>_OPTIONS` environment variable passed to a service at start up.

    Examples:
        >>> parse_options("-Z --conf 'RealMemory=60000 CPUs=16' --conf-server 'localhost:6817'")
        {'-Z': True, '--conf': 'RealMemory=60000 CPUs=16', '--conf-server': 'localhost:6817'}
    """
    result: dict[str, Any] = {}

    opts = shlex.split(options)
    for i, opt in enumerate(opts):
        if opt.startswith("-"):
            # If `opt` is a boolean flag with no ensuing arguments.
            if i + 1 == len(opts) or opts[i + 1].startswith("-"):
                result[opt] = True
            else:
                result[opt] = opts[i + 1]

    return result
