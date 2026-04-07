# charmed-slurm-oci-runtime-interface

Integration interface implementation for the `slurm_oci_runtime` charm integration interface.

This package provides the `OCIRuntimeProvider` and `OCIRuntimeRequirer` classes used
to integrate OCI runtime charms (e.g. Apptainer) with `slurmctld`.

## Usage

```python
from charmed_slurm_oci_runtime_interface import (
    OCIRuntimeData,
    OCIRuntimeDisconnectedEvent,
    OCIRuntimeReadyEvent,
    OCIRuntimeProvider,
    OCIRuntimeRequirer,
)
```
