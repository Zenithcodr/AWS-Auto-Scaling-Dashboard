#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
OS_NAME="$(uname -s)"

if [[ "$OS_NAME" != "Darwin" && "${ALLOW_NON_MAC_LOCAL_RUN:-0}" != "1" ]]; then
  echo "This dashboard run script is intended for your Mac." >&2
  echo "AWS should host only Terraform-created resources and the Ansible workload target." >&2
  echo "Set ALLOW_NON_MAC_LOCAL_RUN=1 only for CI or intentional local debugging." >&2
  exit 1
fi

cd "$PROJECT_DIR"

"${PROJECT_DIR}/scripts/sync_dashboard_env.sh"

./scripts/check_devops_prereqs.sh

export DASHBOARD_RUNTIME_POLICY=local_only
export ALLOW_DASHBOARD_ON_AWS=false
export LOCAL_DEMO_WORK_ENABLED="${LOCAL_DEMO_WORK_ENABLED:-false}"

echo "Starting dashboard locally on this Mac at http://127.0.0.1:5000"
echo "AWS resources remain remote and are managed through Terraform and Ansible."

docker compose up --build
