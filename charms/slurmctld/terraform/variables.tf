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
  description = "Application name"
  type        = string
  default     = "slurmctld"
}

variable "base" {
  description = "Charm base"
  type        = string
  default     = "ubuntu@24.04"
}

variable "channel" {
  description = "Charm channel"
  type        = string
  default     = "latest/edge"
}

variable "config" {
  description = "Charm configuration"
  type        = map(string)
  default     = {}
}

variable "constraints" {
  description = "Deployment constraints"
  type        = string
  default     = ""
}

variable "model_uuid" {
  description = "Model UUID"
  type        = string
}

variable "revision" {
  description = "Charm revision"
  type        = number
  nullable    = true
  default     = null
}

variable "units" {
  description = "Number of units"
  type        = number
  default     = 1
}
