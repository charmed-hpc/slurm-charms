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

output "application" {
  description = "The deployed slurmctld application resource."
  value       = juju_application.slurmctld
}

output "provides" {
  description = "Map of provides endpoint names."
  value = {
    cos_agent = "cos-agent"
    mount     = "mount"
  }
}

output "requires" {
  description = "Map of requires endpoint names."
  value = {
    influxdb    = "influxdb"
    sackd       = "sackd"
    oci_runtime = "oci-runtime"
    slurmd      = "slurmd"
    slurmdbd    = "slurmdbd"
    slurmrestd  = "slurmrestd"
    smtp        = "smtp"
  }
}
