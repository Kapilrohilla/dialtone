#!/usr/bin/env bash
# One-time setup for a fresh Ubuntu 22.04/24.04 VM: Docker + firewall.
# Usage: sudo scripts/bootstrap-server.sh <provider-ip-or-cidr> [more ...]
# The provider IPs are the only sources allowed to reach SIP port 5060.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "run with sudo" >&2; exit 1; fi
if (($# == 0)); then echo "usage: $0 <sip-provider-ip/cidr> [...]" >&2; exit 1; fi

if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
[[ -n "${SUDO_USER:-}" ]] && usermod -aG docker "$SUDO_USER"

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
