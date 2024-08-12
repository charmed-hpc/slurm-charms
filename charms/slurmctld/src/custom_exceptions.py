#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

"""This module has custom exceptions for slurmctld-operator.

Exception: IngressAddressUnavailableError
"""


class IngressAddressUnavailableError(Exception):
    """Exception raised when Ingress Adreess is not yet availability."""

    def __init__(self, message="Ingress address unavailable"):
        self.message = message
        super().__init__(self.message)
