# Copyright 2025 Omnivector, LLC
# See LICENSE file for licensing details.

"""Slurmctld common utils."""
import secrets
import string


def generate_random_string(length=20):
    """Generate a pseudo-random string."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
