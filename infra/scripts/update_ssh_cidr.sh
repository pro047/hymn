#!/usr/bin/env bash
set -euo pipefail

# Fetch current public IP and write allowed_ssh_cidr into an auto tfvars file.
# Usage: ./scripts/update_ssh_cidr.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ip="$(curl -s --max-time 5 https://ifconfig.me)"
if ! [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
  echo "Failed to detect public IPv4 (got: $ip)" >&2
  exit 1
fi

cat > ssh_ip.auto.tfvars <<EOF
allowed_ssh_cidr = ["$ip/32"]
EOF

echo "Wrote ssh_ip.auto.tfvars with allowed_ssh_cidr=[\"$ip/32\"]."
echo "Next: cd infra && terraform plan/apply (auto.tfvars will be picked up)."
