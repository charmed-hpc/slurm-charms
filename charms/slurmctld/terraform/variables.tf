# Copyright 2024-2026 Canonical Ltd.
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

variable "app_name" {
  description = "Name of the Juju application deployed from this charm."
  type        = string
  default     = "slurmctld"
}

variable "base" {
  description = "Base operating system to use for the deployed application (for example, ubuntu@24.04)."
  type        = string
  default     = "ubuntu@24.04"
}

variable "channel" {
  description = "Channel of the charm to deploy from."
  type        = string
  default     = "latest/edge"
}

variable "config" {
  description = "Map of charm configuration options."
  type        = map(string)
  default     = {}
}

variable "constraints" {
  description = "Constraints to apply to the deployed application."
  type        = string
  default     = null
}

variable "machines" {
  description = "List of machine IDs to place units on."
  type        = set(string)
  default     = []
}

variable "model_uuid" {
  description = "UUID of the Juju model to deploy the charm into."
  type        = string
}

variable "revision" {
  description = "Revision of the charm to deploy. Null deploys the latest revision on the given channel."
  type        = number
  nullable    = true
  default     = null
}

variable "units" {
  description = "Number of application units to deploy."
  type        = number
  default     = 1
}
