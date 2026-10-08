variable "project_id" {
  type    = string
  default = "carrum-agent-pilot-dev"
}

variable "region" {
  type    = string
  default = "asia-south1"
}

variable "zone" {
  type    = string
  default = "asia-south1-c"
}

variable "name" {
  description = "Name for the VM; also used as the network tag and resource prefix."
  type        = string
  default     = "ai-calling"
}

variable "machine_type" {
  description = "e2-medium is fine for ~2 calls; use e2-standard-4+ for real traffic."
  type        = string
  default     = "e2-medium"
}

variable "boot_disk_size_gb" {
  type    = number
  default = 10
}

variable "sip_provider_cidrs" {
  description = "SIP provider signalling IPs/CIDRs allowed to reach port 5060. Empty = SIP port closed."
  type        = list(string)
  default     = []
}
