#!/usr/bin/env bash

set -euo pipefail

WORKER_LABEL="${1:-cloud-devops-load-worker}"
REQUEST_URL="${2:-}"
CONNECT_TIMEOUT="${CURL_CONNECT_TIMEOUT:-5}"
MAX_TIME="${CURL_MAX_TIME:-45}"

if [[ -z "$REQUEST_URL" ]]; then
  echo "[$WORKER_LABEL] Missing request URL." >&2
  exit 1
fi

trap 'exit 0' TERM INT HUP

while true; do
  curl -s --fail --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" "$REQUEST_URL" >/dev/null || sleep 1
done
