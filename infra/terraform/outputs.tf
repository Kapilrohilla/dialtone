output "public_ip" {
  description = "Point your SIP provider at sip:<public_ip>:5060"
  value       = google_compute_address.ip.address
}

output "internal_ip" {
  description = "Agent VMs in phase 2 connect to ws://<internal_ip>:7880"
  value       = google_compute_instance.vm.network_interface[0].network_ip
}

output "ssh_command" {
  value = "gcloud compute ssh ${google_compute_instance.vm.name} --project ${var.project_id} --zone ${var.zone}"
}
