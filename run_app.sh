#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HOST="${APP_BIND_HOST:-127.0.0.1}"
PORT="${APP_BIND_PORT:-5000}"
WORKERS="${GUNICORN_WORKERS:-2}"
THREADS="${GUNICORN_THREADS:-4}"
TIMEOUT="${GUNICORN_TIMEOUT:-180}"
DISPLAY_HOST="$HOST"

export DASHBOARD_RUNTIME_POLICY="${DASHBOARD_RUNTIME_POLICY:-local_only}"
export ALLOW_DASHBOARD_ON_AWS="${ALLOW_DASHBOARD_ON_AWS:-false}"
export LOCAL_DEMO_WORK_ENABLED="${LOCAL_DEMO_WORK_ENABLED:-false}"

cd "${SCRIPT_DIR}"

if [[ -f "${SCRIPT_DIR}/lab.env" ]]; then
  "${SCRIPT_DIR}/scripts/sync_dashboard_env.sh"
fi

if [[ -f "${SCRIPT_DIR}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.venv/bin/activate"
fi

if ! command -v gunicorn >/dev/null 2>&1; then
  echo "Missing gunicorn. Install Python dependencies first: .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if [[ "$DISPLAY_HOST" == "0.0.0.0" ]]; then
  DISPLAY_HOST="127.0.0.1"
fi

echo "Starting local Mac Cloud & DevOps dashboard with Gunicorn..."
echo "Dashboard: http://${DISPLAY_HOST}:${PORT}"
echo "Listening on ${HOST}:${PORT}"

exec gunicorn \
  --bind "${HOST}:${PORT}" \
  --workers "${WORKERS}" \
  --threads "${THREADS}" \
  --timeout "${TIMEOUT}" \
  --access-logfile - \
  --error-logfile - \
  app:app
