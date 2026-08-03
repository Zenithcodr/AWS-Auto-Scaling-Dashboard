#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
OUTPUT_ENV="${PROJECT_DIR}/.env"

LAB_PROJECT_DIR="$PROJECT_DIR"
export LAB_PROJECT_DIR
# shellcheck disable=SC1091
. "${SCRIPT_DIR}/load_lab_env.sh"

write_env_line() {
  local key="$1"
  local value="${2:-}"
  printf '%s=%s\n' "$key" "$value"
}

umask 077
{
  write_env_line FLASK_ENV "${FLASK_ENV:-production}"
  write_env_line APP_HOST "${APP_HOST:-127.0.0.1}"
  write_env_line APP_PORT "${APP_PORT:-5000}"
  write_env_line DASHBOARD_RUNTIME_POLICY "${DASHBOARD_RUNTIME_POLICY:-local_only}"
  write_env_line ALLOW_DASHBOARD_ON_AWS "${ALLOW_DASHBOARD_ON_AWS:-false}"
  write_env_line LOCAL_DEMO_WORK_ENABLED "${LOCAL_DEMO_WORK_ENABLED:-false}"
  printf '\n'

  write_env_line AWS_REGION "${AWS_REGION:-us-east-1}"
  write_env_line AWS_PROFILE "${AWS_PROFILE:-}"
  write_env_line AWS_ACCESS_KEY_ID "${AWS_ACCESS_KEY_ID:-}"
  write_env_line AWS_SECRET_ACCESS_KEY "${AWS_SECRET_ACCESS_KEY:-}"
  write_env_line AWS_SESSION_TOKEN "${AWS_SESSION_TOKEN:-}"
  write_env_line USE_IAM_ROLE "${USE_IAM_ROLE:-false}"
  printf '\n'

  write_env_line MONITORING_LABEL "${MONITORING_LABEL:-AWS Auto-Scaling Monitoring & Control Dashboard}"
  write_env_line EC2_TAG_KEY "${EC2_TAG_KEY:-}"
  write_env_line EC2_TAG_VALUE "${EC2_TAG_VALUE:-}"
  write_env_line AUTO_SCALING_GROUP_NAME "${AUTO_SCALING_GROUP_NAME:-}"
  write_env_line LOAD_BALANCER_ARN "${LOAD_BALANCER_ARN:-}"
  write_env_line TARGET_GROUP_ARN "${TARGET_GROUP_ARN:-}"
  write_env_line AWS_METRIC_WINDOW_MINUTES "${AWS_METRIC_WINDOW_MINUTES:-60}"
  write_env_line AWS_METRIC_PERIOD_SECONDS "${AWS_METRIC_PERIOD_SECONDS:-60}"
  write_env_line POLL_INTERVAL_SECONDS "${POLL_INTERVAL_SECONDS:-10}"
  printf '\n'

  write_env_line SCALING_MODE "${SCALING_MODE:-custom}"
  write_env_line SCALE_OUT_CPU_THRESHOLD "${SCALE_OUT_CPU_THRESHOLD:-70}"
  write_env_line SCALE_IN_CPU_THRESHOLD "${SCALE_IN_CPU_THRESHOLD:-30}"
  write_env_line SCALER_SCALE_OUT_CONFIRMATION_SAMPLES "${SCALER_SCALE_OUT_CONFIRMATION_SAMPLES:-1}"
  write_env_line SCALER_SCALE_IN_CONFIRMATION_SAMPLES "${SCALER_SCALE_IN_CONFIRMATION_SAMPLES:-2}"
  write_env_line SCALER_REQUEST_SIGNAL_THRESHOLD "${SCALER_REQUEST_SIGNAL_THRESHOLD:-3}"
  write_env_line SCALER_SCALE_OUT_REQUEST_SIGNAL_THRESHOLD "${SCALER_SCALE_OUT_REQUEST_SIGNAL_THRESHOLD:-1}"
  write_env_line SCALER_FAST_SCALE_OUT_STEP "${SCALER_FAST_SCALE_OUT_STEP:-2}"
  write_env_line SCALER_FAST_SCALE_OUT_CPU_RATIO "${SCALER_FAST_SCALE_OUT_CPU_RATIO:-1.05}"
  write_env_line SCALER_FAST_SCALE_IN_STEP "${SCALER_FAST_SCALE_IN_STEP:-2}"
  write_env_line SCALER_FAST_SCALE_IN_CPU_RATIO "${SCALER_FAST_SCALE_IN_CPU_RATIO:-0.5}"
  write_env_line SCALER_IDLE_COLLAPSE_CPU_RATIO "${SCALER_IDLE_COLLAPSE_CPU_RATIO:-0.8}"
  write_env_line SCALER_MIN_INSTANCES "${SCALER_MIN_INSTANCES:-1}"
  write_env_line SCALER_MAX_INSTANCES "${SCALER_MAX_INSTANCES:-4}"
  write_env_line SCALER_HARD_MIN_INSTANCES "${SCALER_HARD_MIN_INSTANCES:-1}"
  write_env_line SCALER_HARD_MAX_INSTANCES "${SCALER_HARD_MAX_INSTANCES:-10}"
  write_env_line SCALER_COOLDOWN_SECONDS "${SCALER_COOLDOWN_SECONDS:-60}"
  printf '\n'

  write_env_line CONTROL_ENABLED "${CONTROL_ENABLED:-true}"
  write_env_line CONTROL_API_TOKEN "${CONTROL_API_TOKEN:-replace-with-a-random-token}"
  write_env_line CONTROL_ALLOW_FORCE "${CONTROL_ALLOW_FORCE:-false}"
  printf '\n'

  write_env_line LOG_TO_S3 "${LOG_TO_S3:-false}"
  write_env_line S3_LOG_BUCKET "${S3_LOG_BUCKET:-}"
  write_env_line METRICS_CSV_PATH "${METRICS_CSV_PATH:-data/metrics.csv}"
  write_env_line EVENTS_CSV_PATH "${EVENTS_CSV_PATH:-data/events.csv}"
  write_env_line SQLITE_PATH "${SQLITE_PATH:-data/metrics.db}"
  write_env_line CONTROLLER_STATE_PATH "${CONTROLLER_STATE_PATH:-data/controller_state.json}"
  write_env_line DEMO_WORK_MAX_ITERATIONS "${DEMO_WORK_MAX_ITERATIONS:-8000000}"
} > "$OUTPUT_ENV"

chmod 600 "$OUTPUT_ENV"
echo "Synced dashboard environment to ${OUTPUT_ENV}"
