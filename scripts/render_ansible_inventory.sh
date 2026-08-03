#!/usr/bin/env bash

set -euo pipefail

REGION="${1:-${AWS_REGION:-us-east-1}}"
PROJECT_NAME="${2:-cloud-devops-autoscaling}"
OUTPUT_PATH="${3:-ansible/inventory.generated.ini}"
ANSIBLE_USER="${ANSIBLE_USER:-ec2-user}"
PRIVATE_KEY_FILE="${ANSIBLE_PRIVATE_KEY_FILE:-}"

mkdir -p "$(dirname "$OUTPUT_PATH")"

INSTANCE_OUTPUT="$(
  aws ec2 describe-instances \
    --region "$REGION" \
    --filters \
      "Name=tag:Project,Values=${PROJECT_NAME}" \
      "Name=instance-state-name,Values=running" \
    --query 'Reservations[].Instances[].[InstanceId,PublicDnsName,PublicIpAddress]' \
    --output text
)"

{
  echo "[demo_workload]"
  while IFS=$'\t' read -r instance_id public_dns public_ip _; do
    [[ -z "${instance_id:-}" || "$instance_id" == "None" ]] && continue
    public_dns="${public_dns:-}"
    public_ip="${public_ip:-}"
    host="$public_dns"
    if [[ -z "$host" || "$host" == "None" ]]; then
      host="$public_ip"
    fi
    if [[ -n "$host" && "$host" != "None" ]]; then
      inventory_line="${instance_id} ansible_host=${host} ansible_user=${ANSIBLE_USER}"
      if [[ -n "$PRIVATE_KEY_FILE" ]]; then
        inventory_line="${inventory_line} ansible_ssh_private_key_file=${PRIVATE_KEY_FILE}"
      fi
      echo "$inventory_line"
    fi
  done <<< "$INSTANCE_OUTPUT"
} > "$OUTPUT_PATH"

if ! grep -q "ansible_host=" "$OUTPUT_PATH"; then
  echo "No running Terraform-created EC2 instances with public DNS/IP were found for Project=${PROJECT_NAME} in ${REGION}." >&2
  echo "Inventory was still written to ${OUTPUT_PATH}." >&2
  exit 1
fi

echo "Wrote Ansible inventory to ${OUTPUT_PATH}"
