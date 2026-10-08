#!/usr/bin/env bash
# One-time setup for a fresh Debian/Ubuntu VM: Docker, plus an optional ufw firewall.
# Usage: sudo scripts/bootstrap-server.sh [<provider-ip-or-cidr> ...]
# With provider IPs, ufw is enabled and only they can reach SIP port 5060.
# Without them, ufw is skipped (e.g. on GCP, where VPC firewall rules are used).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "run with sudo" >&2; exit 1; fi

if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  distro=$(. /etc/os-release && echo "$ID")  # debian or ubuntu
  curl -fsSL "https://download.docker.com/linux/${distro}/gpg" -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${distro} $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
apt-get install -y make git
[[ -n "${SUDO_USER:-}" ]] && usermod -aG docker "$SUDO_USER"

if (($# == 0)); then
  echo "no provider IPs given: skipping ufw (configure the cloud firewall instead)"
  exit 0
fi

apt-get install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
for src in "$@"; do
  ufw allow from "$src" to any port 5060 proto udp comment 'SIP signalling'
  ufw allow from "$src" to any port 5060 proto tcp comment 'SIP signalling'
done
ufw allow 10000:20000/udp comment 'SIP RTP media'
ufw allow 7881/tcp comment 'WebRTC TCP'
ufw allow 50000:60000/udp comment 'WebRTC UDP'
# 7880 (API) is intentionally NOT public. Agents on other VMs should reach it
# over the private network: ufw allow from <private-subnet> to any port 7880
ufw --force enable
ufw status verbose
