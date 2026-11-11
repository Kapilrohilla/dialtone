terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  # Local state for now. To share state with the team, create a bucket and switch:
  # backend "gcs" {
  #   bucket = "<your-project-id>-tfstate"
  #   prefix = "dialtone"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone

  # Don't add a goog-terraform-provisioned label to adopted resources.
  add_terraform_attribution_label = false
}
