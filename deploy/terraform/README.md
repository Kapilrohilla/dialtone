# Terraform: optional GCP example

An optional, generic example that creates a single GCP VM for the Dialtone stack. Nothing else in the repo
depends on it; any Linux host with Docker works.

| Resource | Terraform address |
|---|---|
| VM `<name>` (default `dialtone`, e2-medium, Debian 13) | `google_compute_instance.vm` |
| Static IP `<name>-ip` | `google_compute_address.ip` |
| Firewall `<name>-allow-media` (RTP + WebRTC) | `google_compute_firewall.media` |
| Firewall `<name>-allow-sip` (5060, provider IPs only) | `google_compute_firewall.sip`, created once `sip_provider_cidrs` is set |

Copy `terraform.tfvars.example` to `terraform.tfvars` (gitignored) and set `project_id`; it has no default.
Then provision the VM with `deploy/bootstrap-server.sh` and ship code with `make deploy GCP_PROJECT=<project_id>`.

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
- **Grow the disk:** increase `boot_disk_size_gb` (100 GB by default; call recordings live on it). GCP disks only grow; shrinking means a new disk.

## Not managed here

- **SSH keys** (`metadata.ssh-keys`): added per user by `gcloud compute ssh`.
- **The `goog-ops-agent-policy` label:** owned by the Ops Agent policy.
- **Default VPC and firewall rules:** shared with other VMs in the project.

## State

State is local (`terraform.tfstate`, gitignored). Before others start running Terraform, move it to a GCS bucket using the commented `backend "gcs"` block in [versions.tf](versions.tf).
