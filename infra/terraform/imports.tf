# These resources were first created by hand (console/gcloud) and adopted into
# Terraform. Import blocks are no-ops once the resources are in state.

import {
  to = google_compute_address.ip
  id = "projects/${var.project_id}/regions/${var.region}/addresses/${var.name}-ip"
}

import {
  to = google_compute_instance.vm
  id = "projects/${var.project_id}/zones/${var.zone}/instances/${var.name}"
}

import {
  to = google_compute_firewall.media
  id = "projects/${var.project_id}/global/firewalls/${var.name}-allow-media"
}

import {
  to = google_compute_firewall.sip[0]
  id = "projects/${var.project_id}/global/firewalls/${var.name}-allow-sip"
}
