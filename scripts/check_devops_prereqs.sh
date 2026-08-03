#!/usr/bin/env bash

set -euo pipefail

missing=()

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    missing+=("$command_name")
  fi
}

require_command docker
require_command terraform
require_command ansible-playbook
require_command aws
require_command curl
require_command python3

if ! docker compose version >/dev/null 2>&1; then
  missing+=("docker compose")
fi

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Missing required Cloud & DevOps tools:" >&2
  for item in "${missing[@]}"; do
    echo "- $item" >&2
  done
  exit 1
fi

echo "Required Cloud & DevOps tools are available:"
echo "- Docker and Docker Compose"
echo "- Terraform"
echo "- Ansible"
echo "- AWS CLI"
echo "- curl"
echo "- Python 3"
