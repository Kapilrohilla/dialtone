# Terraform: ai-calling GCP infra

Tracks the GCP resources in **Carrum Agent Pilot Dev** (`carrum-agent-pilot-dev`).

| Resource | Terraform address |
|---|---|
| VM `ai-calling` (e2-medium, asia-south1-c, Debian 13) | `google_compute_instance.vm` |
| Static IP `ai-calling-ip` (34.93.218.151) | `google_compute_address.ip` |
| Firewall `ai-calling-allow-media` (RTP + WebRTC) | `google_compute_firewall.media` |
| Firewall `ai-calling-allow-sip` (5060, provider IPs only) | `google_compute_firewall.sip`, created once `sip_provider_cidrs` is set |

These resources were created by hand first and adopted with the `import` blocks in [imports.tf](imports.tf).

## Auth

Terraform uses Application Default Credentials, which are separate from your `gcloud` login. Either log in once:

```bash
gcloud auth application-default login
```

or, per shell session, reuse your gcloud login:

```bash
export GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)
```

## Usage

```bash
terraform init
terraform plan      # should say "No changes" when nothing has drifted
terraform apply
```

Common changes:

- **Open SIP to your provider:** in `terraform.tfvars`, set `sip_provider_cidrs = ["1.2.3.4/32", ...]`.
- **Resize the VM:** set `machine_type = "e2-standard-4"`. The VM stops briefly; the static IP stays.
- **Grow the disk:** increase `boot_disk_size_gb`.

## Not managed here

- **SSH keys** (`metadata.ssh-keys`): added per user by `gcloud compute ssh`.
- **The `goog-ops-agent-policy` label:** owned by the Ops Agent policy.
- **Default VPC and firewall rules:** shared with other VMs in the project.

## State

State is local (`terraform.tfstate`, gitignored). Before others start running Terraform, move it to a GCS bucket using the commented `backend "gcs"` block in [versions.tf](versions.tf).
