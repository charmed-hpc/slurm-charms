# charmed-slurm-slurmctld-interface

Integration interface implementation for the `slurmctld` Juju charm integration.

This package provides the `SlurmctldProvider` and `SlurmctldRequirer` base classes
used to build all Slurm integration interfaces, along with common data structures,
events, and utilities shared between Slurm-related integration interfaces.

## Usage

```python
from charmed_slurm_slurmctld_interface import (
    ControllerData,
    SlurmctldProvider,
    SlurmctldRequirer,
    controller_ready,
)
```

