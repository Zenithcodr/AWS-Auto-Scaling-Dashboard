#!/usr/bin/env bash

# Source this file from the project root:
#   . ./scripts/load_lab_env.sh

LAB_PROJECT_DIR="${LAB_PROJECT_DIR:-$(pwd)}"
LAB_ENV_FILE="${LAB_ENV_FILE:-${LAB_PROJECT_DIR}/lab.env}"

if [[ ! -f "$LAB_ENV_FILE" ]]; then
  echo "Missing lab env file: ${LAB_ENV_FILE}" >&2
  echo "Create it with: cp lab.env.example lab.env" >&2
  return 1 2>/dev/null || exit 1
fi

set -a
# shellcheck disable=SC1090
. "$LAB_ENV_FILE"
set +a

export AWS_REGION="${AWS_REGION:-us-east-1}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"
export LAB_REGION="${LAB_REGION:-$AWS_REGION}"

if [[ -z "${LOAD_TEST_TARGET_BASE:-}" && -n "${ALB_DNS_NAME:-}" && "$ALB_DNS_NAME" != PASTE_* ]]; then
  export LOAD_TEST_TARGET_BASE="http://${ALB_DNS_NAME}/demo/work"
fi

export ANSIBLE_USER="${ANSIBLE_USER:-ec2-user}"
if [[ -n "${LAB_PRIVATE_KEY_FILE:-}" && "$LAB_PRIVATE_KEY_FILE" != "/absolute/path/to/"* ]]; then
  export ANSIBLE_PRIVATE_KEY_FILE="$LAB_PRIVATE_KEY_FILE"
fi

export TF_VAR_aws_region="$LAB_REGION"
export TF_VAR_vpc_id="${LAB_VPC_ID:-}"
export TF_VAR_public_subnet_ids="${LAB_PUBLIC_SUBNET_IDS:-[]}"
export TF_VAR_ami_id="${LAB_AMI_ID:-}"
export TF_VAR_key_name="${LAB_KEY_NAME:-}"
if [[ -n "${LAB_SSH_CIDR:-}" && "$LAB_SSH_CIDR" != "YOUR_PUBLIC_IP/32" ]]; then
  export TF_VAR_ssh_allowed_cidr_blocks="[\"${LAB_SSH_CIDR}\"]"
else
  export TF_VAR_ssh_allowed_cidr_blocks="[]"
fi

echo "Loaded lab environment from ${LAB_ENV_FILE}"
echo "Region: ${LAB_REGION}"
echo "Terraform variables are available as TF_VAR_*"
echo "Ansible key: ${ANSIBLE_PRIVATE_KEY_FILE:-not set yet}"
echo "Load target: ${LOAD_TEST_TARGET_BASE:-not set yet}"
