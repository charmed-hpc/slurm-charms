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

uv := require("uv")

export PY_COLORS := "1"
export PYTHONBREAKPOINT := "pdb.set_trace"

uv_run := "uv run --frozen --extra dev"

[private]
default:
    @just help

# Prepare the local environment
setup: env

# Clean project directory
clean: lock
    {{uv_run}} repository.py clean

# Apply static checks
check: fmt lint typecheck

# Run tests for specified targets, or all tests if none specified
test *targets:
    #!/usr/bin/env bash
    if [ "{{targets}}" = "" ]; then
        just test-all
        exit 0
    fi

    for target in {{targets}}; do
        if just --show $target > /dev/null 2>&1; then
            echo "Running $target tests..."
            just $target
        else
            echo "Error: test target '$target' not found." >&2
            exit 1
        fi
    done

# Run all test suites
test-all: unit integration

# Run unit tests
unit *args: lock
    {{uv_run}} repository.py unit {{args}}

# Run integration tests
integration *args: lock
    {{uv_run}} repository.py integration {{args}}

# Regenerate uv.lock
lock:
    uv lock

# Create a uv development environment
env: lock
    uv sync --extra dev

# Upgrade uv.lock with the latest dependencies
upgrade:
    uv lock --upgrade

# Apply formatting standards
fmt: lock
    {{uv_run}} repository.py fmt

# Check files against style standards
lint: lock
    {{uv_run}} repository.py lint

# Perform type checking
typecheck: lock
    {{uv_run}} repository.py typecheck

# Run action on monorepo. For a full list of actions, run `just repo`
repo *args: lock
    {{uv_run}} repository.py {{args}}

# Show available recipes
help:
    @just --list --unsorted
