data "google_compute_default_service_account" "default" {}

# Static public IP: the SIP provider routes calls here, so it must never change.
resource "google_compute_address" "ip" {
  name   = "${var.name}-ip"
  region = var.region
}

resource "google_compute_instance" "vm" {
  name                       = var.name
  zone                       = var.zone
  machine_type               = var.machine_type
  tags                       = [var.name]
  allow_stopping_for_update  = true
  key_revocation_action_type = "NONE"
  enable_display             = false

  boot_disk {
    auto_delete = true
    device_name = var.name

    initialize_params {
      image = "projects/debian-cloud/global/images/debian-13-trixie-v20261006"
      size  = var.boot_disk_size_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    network    = "default"
    subnetwork = "default"

    access_config {
      nat_ip       = google_compute_address.ip.address
      network_tier = "PREMIUM"
    }
  }

  metadata = {
    enable-osconfig = "TRUE"
  }

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
    preemptible         = false
    provisioning_model  = "STANDARD"
  }

  shielded_instance_config {
    enable_secure_boot          = false
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  service_account {
    email = data.google_compute_default_service_account.default.email
    scopes = [
      "https://www.googleapis.com/auth/devstorage.read_only",
      "https://www.googleapis.com/auth/logging.write",
      "https://www.googleapis.com/auth/monitoring.write",
      "https://www.googleapis.com/auth/service.management.readonly",
      "https://www.googleapis.com/auth/servicecontrol",
      "https://www.googleapis.com/auth/trace.append",
    ]
  }

  lifecycle {
    ignore_changes = [
      # SSH keys are added by `gcloud compute ssh` per user.
      metadata["ssh-keys"],
      # The image only matters at creation; don't recreate the VM when Debian publishes a new one.
      boot_disk[0].initialize_params[0].image,
      # Set by the Ops Agent policy, not by us.
      labels["goog-ops-agent-policy"],
    ]
  }
}

# Call audio (RTP from the SIP provider) and WebRTC media. Must be open to the world.
resource "google_compute_firewall" "media" {
  name        = "${var.name}-allow-media"
  network     = "default"
  direction   = "INGRESS"
  description = "SIP RTP audio + WebRTC media for LiveKit"

  source_ranges = ["0.0.0.0/0"]
  target_tags   = [var.name]

  allow {
    protocol = "udp"
    ports    = ["10000-20000"]
  }

  allow {
    protocol = "udp"
    ports    = ["50000-60000"]
  }

  allow {
    protocol = "tcp"
    ports    = ["7881"]
  }
}

# SIP signalling, only from the provider. Created once sip_provider_cidrs is set.
resource "google_compute_firewall" "sip" {
  count       = length(var.sip_provider_cidrs) > 0 ? 1 : 0
  name        = "${var.name}-allow-sip"
  network     = "default"
  direction   = "INGRESS"
  description = "SIP signalling from the SIP trunk provider"

  source_ranges = var.sip_provider_cidrs
  target_tags   = [var.name]

  allow {
    protocol = "udp"
    ports    = ["5060"]
  }

  allow {
    protocol = "tcp"
    ports    = ["5060"]
  }
}
