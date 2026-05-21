# Terraform module for slurmdbd

This is a Terraform module facilitating the deployment of the slurmdbd charm using
the [Juju Terraform provider](https://github.com/juju/terraform-provider-juju).
For more information, refer to the
[documentation](https://registry.terraform.io/providers/juju/juju/latest/docs)
for the Juju Terraform provider.

## Requirements

- Terraform >= 1.0
- Juju Terraform provider >= 1.0.0, < 2.0.0
- An existing Juju model

## API

### Inputs

| Name          | Type        | Description                                                              | Default          | Required |
|---------------|-------------|--------------------------------------------------------------------------|------------------|:--------:|
| `app_name`    | string      | Name of the Juju application deployed from this charm.                   | `"slurmdbd"`     |          |
| `base`        | string      | Base operating system to use for the deployed application.               | `"ubuntu@24.04"` |          |
| `channel`     | string      | Channel of the charm to deploy from.                                     | `"latest/edge"`  |          |
| `config`      | map(string) | Map of charm configuration options.                                      | `{}`             |          |
| `constraints` | string      | Constraints to apply to the deployed application.                        | `null`           |          |
| `machines`    | set(string) | List of machine IDs to place units on.                                   | `[]`             |          |
| `model_uuid`  | string      | UUID of the Juju model to deploy the charm into.                         |                  |    Y     |
| `revision`    | number      | Revision of the charm to deploy. Null deploys the latest on the channel. | `null`           |          |
| `units`       | number      | Number of application units to deploy.                                   | `1`              |          |

### Outputs

| Name          | Description                              |
|---------------|------------------------------------------|
| `application` | The deployed `juju_application` resource |
| `provides`    | Map of `provides` endpoint names         |
| `requires`    | Map of `requires` endpoint names         |

The `provides` output exposes the following endpoint names:

| Key        | Endpoint name |
|------------|---------------|
| `slurmctld` | `slurmctld`  |

The `requires` output exposes the following endpoint names:

| Key        | Endpoint name |
|------------|---------------|
| `database` | `database`    |

## Usage

Ensure that Terraform is aware of the Juju model dependency of the charm module.

```hcl
module "slurmdbd" {
  source     = "git::https://github.com/canonical/slurm-charms//charms/slurmdbd/terraform"
  model_uuid = juju_model.my_model.uuid
}
```

To deploy this module with its required dependency, you can run the following
command:

```shell
terraform apply -var="model_uuid=<MODEL_UUID>" -auto-approve
```
