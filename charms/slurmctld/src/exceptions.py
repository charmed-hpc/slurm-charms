# Copyright (c) 2024 Omnivector Corp
# See LICENSE file for licensing details.

"""Custom exceptions for the slurmctld operator."""


class IngressAddressUnavailableError(Exception):
    """Exception raised when a slurm operation failed."""

    @property
    def message(self) -> str:
        """Return message passed as argument to exception."""
        return self.args[0]
