#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${SCRIPT_DIR}/.load-test"
PID_FILE="${STATE_DIR}/pids"
META_FILE="${STATE_DIR}/meta"
LOG_FILE="${STATE_DIR}/load-test.log"
WORKER_SCRIPT="${SCRIPT_DIR}/load_test_worker.sh"
WORKER_PREFIX="${LOAD_WORKER_PREFIX:-cloud-devops-load-worker}"
DEFAULT_TARGET_BASE="${LOAD_TEST_TARGET_BASE:-}"
HARD_STOP_PATTERN="${WORKER_PREFIX}|cppe-load-worker"

usage() {
  cat <<'EOF'
Usage:
  ./load_test.sh start [light|medium|heavy|scaleout70|spike|flood] [target_base_url]
  ./load_test.sh probe [light|medium|heavy|scaleout70|spike|flood] [target_base_url]
  ./load_test.sh stop
  ./load_test.sh restart [light|medium|heavy|scaleout70|spike|flood] [target_base_url]
  ./load_test.sh status
  ./load_test.sh burst [count] [iterations] [target_base_url]

Examples:
  export LOAD_TEST_TARGET_BASE=http://your-alb-dns/demo/work
  ./load_test.sh probe scaleout70
  ./load_test.sh start scaleout70
  ./load_test.sh start spike http://your-alb-dns/demo/work
  ./load_test.sh burst 40 2500000 http://your-alb-dns/demo/work
  ./load_test.sh stop

Behavior:
  start/restart -> sustained constant load until you run ./load_test.sh stop
  probe         -> checks /healthz and a lightweight /demo/work request before load starts
  burst         -> one-time batch of requests, then exits
  default       -> scaleout70 when no profile is supplied

Profiles:
  light      -> 8 workers, short CPU requests
  medium     -> 16 workers, steady CPU requests
  heavy      -> 32 workers, stronger CPU requests
  scaleout70 -> 24 workers, 20-second CPU burn requests designed to push t3.micro CPU above 70%
  spike      -> 48 workers, 25-second CPU burn requests
  flood      -> 72 workers, 30-second CPU burn requests
EOF
}

require_remote_target() {
  local target_base="$1"

  if [[ -z "$target_base" ]]; then
    echo "Missing AWS ALB workload URL." >&2
    echo "Pass http://<alb-dns>/demo/work or set LOAD_TEST_TARGET_BASE." >&2
    echo "Do not load-test the local dashboard; the dashboard runs on your Mac." >&2
    exit 1
  fi

  case "$target_base" in
    http://localhost*|https://localhost*|http://127.0.0.1*|https://127.0.0.1*|http://0.0.0.0*|https://0.0.0.0*)
      echo "Refusing to target the local dashboard for load generation: ${target_base}" >&2
      echo "Use the Terraform-created ALB DNS name ending in /demo/work." >&2
      exit 1
      ;;
  esac

  if [[ "$target_base" != */demo/work* ]]; then
    echo "Target should normally be the AWS ALB /demo/work endpoint." >&2
    echo "Received: ${target_base}" >&2
    exit 1
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

have_command() {
  command -v "$1" >/dev/null 2>&1
}

strip_query_string() {
  local url="$1"
  printf '%s' "${url%%\?*}"
}

derive_health_url() {
  local target_base="$1"
  local without_query
  without_query="$(strip_query_string "$target_base")"

  if [[ "$without_query" == */demo/work ]]; then
    printf '%s/healthz' "${without_query%/demo/work}"
    return
  fi

  printf '%s/healthz' "${without_query%/}"
}

append_iterations() {
  local base_url="$1"
  local iterations="$2"

  if [[ "$base_url" == *\?* ]]; then
    printf '%s&iterations=%s' "$base_url" "$iterations"
  else
    printf '%s?iterations=%s' "$base_url" "$iterations"
  fi
}

append_work_params() {
  local base_url="$1"
  local iterations="$2"
  local seconds="${3:-0}"
  local request_url

  request_url="$(append_iterations "$base_url" "$iterations")"
  if [[ "$seconds" != "0" && "$seconds" != "0.0" ]]; then
    printf '%s&seconds=%s' "$request_url" "$seconds"
  else
    printf '%s' "$request_url"
  fi
}

set_profile() {
  local profile="${1:-scaleout70}"

  case "$profile" in
    light)
      WORKERS=8
      ITERATIONS=1200000
      WORK_SECONDS=0
      ;;
    medium)
      WORKERS=16
      ITERATIONS=3000000
      WORK_SECONDS=0
      ;;
    heavy)
      WORKERS=32
      ITERATIONS=5000000
      WORK_SECONDS=0
      ;;
    scaleout70|scale70|target70)
      WORKERS=24
      ITERATIONS=5000000
      WORK_SECONDS=20
      ;;
    spike)
      WORKERS=48
      ITERATIONS=7000000
      WORK_SECONDS=25
      ;;
    flood)
      WORKERS=72
      ITERATIONS=8000000
      WORK_SECONDS=30
      ;;
    *)
      echo "Unknown profile: $profile" >&2
      usage
      exit 1
      ;;
  esac
}

ensure_state_dir() {
  mkdir -p "$STATE_DIR"
}

read_pids() {
  PIDS=()
  if [[ -f "$PID_FILE" ]]; then
    while IFS= read -r pid || [[ -n "$pid" ]]; do
      PIDS+=("$pid")
    done <"$PID_FILE"
  fi
}

alive_pids() {
  local alive=()
  read_pids
  for pid in "${PIDS[@]:-}"; do
    if [[ -n "${pid}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      alive+=("$pid")
    fi
  done
  printf '%s\n' "${alive[@]:-}"
}

write_meta() {
  local profile="$1"
  local workers="$2"
  local iterations="$3"
  local seconds="$4"
  local request_url="$5"

  cat >"$META_FILE" <<EOF
PROFILE=$profile
WORKERS=$workers
ITERATIONS=$iterations
SECONDS_PER_REQUEST=$seconds
REQUEST_URL=$request_url
STARTED_AT=$(date '+%Y-%m-%d %H:%M:%S %Z')
EOF
}

read_meta_value() {
  local key="$1"
  if [[ ! -f "$META_FILE" ]]; then
    return
  fi

  awk -F= -v wanted="$key" '$1 == wanted { print substr($0, index($0, "=") + 1) }' "$META_FILE"
}

build_process_pattern() {
  local request_url="${1:-}"
  local target_base="${2:-$DEFAULT_TARGET_BASE}"

  if [[ -z "$request_url" ]]; then
    request_url="$(read_meta_value "REQUEST_URL")"
  fi

  if [[ -n "$request_url" ]]; then
    printf '%s|%s|%s|/demo/work' "$WORKER_PREFIX" "$request_url" "$target_base"
  elif [[ -n "$target_base" ]]; then
    printf '%s|%s|/demo/work' "$WORKER_PREFIX" "$target_base"
  else
    printf '%s' "$WORKER_PREFIX"
  fi
}

matching_processes() {
  local pattern="$1"
  if have_command pgrep; then
    pgrep -af "$pattern" 2>/dev/null || true
  fi
}

probe_endpoint() {
  local label="$1"
  local url="$2"
  local max_time="$3"
  local response_file
  local http_code

  ensure_state_dir
  response_file="$(mktemp "${STATE_DIR}/probe.XXXXXX")"
  http_code="$(curl -sS --connect-timeout 5 --max-time "$max_time" -o "$response_file" -w "%{http_code}" "$url" || true)"

  if [[ "$http_code" == 2* ]]; then
    echo "${label} probe succeeded with HTTP ${http_code}."
    echo "Probe URL: ${url}"
    rm -f "$response_file"
    return 0
  fi

  echo "${label} probe failed for ${url}." >&2
  echo "HTTP code: ${http_code:-000}" >&2
  if [[ "${http_code:-000}" == "000" ]]; then
    echo "No HTTP response was received. The ALB may not have a healthy target, the target group route may be wrong, or the instance app port may be blocked." >&2
  fi
  if [[ -s "$response_file" ]]; then
    echo "Response preview:" >&2
    head -c 400 "$response_file" >&2 || true
    echo >&2
  fi
  rm -f "$response_file"
  return 1
}

probe_target() {
  local profile="${1:-scaleout70}"
  local target_base="${2:-$DEFAULT_TARGET_BASE}"
  local probe_iterations
  local probe_url
  local health_url

  set_profile "$profile"
  require_remote_target "$target_base"
  ensure_state_dir

  probe_iterations="$ITERATIONS"
  if (( probe_iterations > 5000 )); then
    probe_iterations=5000
  fi

  health_url="$(derive_health_url "$target_base")"
  probe_url="$(append_work_params "$target_base" "$probe_iterations" 0)"

  probe_endpoint "Health" "$health_url" 15
  probe_endpoint "Workload" "$probe_url" 30
}

start_load() {
  local profile="${1:-scaleout70}"
  local target_base="${2:-$DEFAULT_TARGET_BASE}"
  local running
  local existing_matches

  require_remote_target "$target_base"

  running="$(alive_pids || true)"
  if [[ -n "$running" ]]; then
    echo "Load test is already running."
    echo "$running"
    exit 1
  fi

  existing_matches="$(matching_processes "$(build_process_pattern "" "$target_base")")"
  if [[ -n "$existing_matches" ]]; then
    echo "Matching load processes already exist. Stop them first." >&2
    printf '%s\n' "$existing_matches" >&2
    exit 1
  fi

  set_profile "$profile"
  ensure_state_dir
  if [[ "${CLOUD_DEVOPS_SKIP_PREFLIGHT:-0}" != "1" ]]; then
    probe_target "$profile" "$target_base"
  fi

  : >"$PID_FILE"
  touch "$LOG_FILE"

  local request_url
  local worker_label
  request_url="$(append_work_params "$target_base" "$ITERATIONS" "${WORK_SECONDS:-0}")"

  for worker_index in $(seq 1 "$WORKERS"); do
    worker_label="${WORKER_PREFIX}-${worker_index}"
    nohup /bin/bash "$WORKER_SCRIPT" "$worker_label" "$request_url" >>"$LOG_FILE" 2>&1 &
    echo "$!" >>"$PID_FILE"
  done

  write_meta "$profile" "$WORKERS" "$ITERATIONS" "${WORK_SECONDS:-0}" "$request_url"

  echo "Started ${WORKERS} workers with profile '${profile}'."
  echo "This is sustained constant load and will keep running until you use ./load_test.sh stop."
  echo "Target: ${request_url}"
  if [[ "${WORK_SECONDS:-0}" != "0" ]]; then
    echo "CPU burn: ${WORK_SECONDS}s per request. Watch for average CPU crossing 70% on the dashboard."
  fi
  echo "Log: ${LOG_FILE}"
}

stop_load() {
  local had_matches=false
  local alive=()
  local request_url=""
  local process_pattern=""
  local attempt=0
  local max_attempts=50
  local found_matches=""
  local line=""

  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    alive+=("$pid")
  done < <(alive_pids || true)

  request_url="$(read_meta_value "REQUEST_URL")"
  process_pattern="$(build_process_pattern "$request_url" "$DEFAULT_TARGET_BASE")"

  if [[ ${#alive[@]} -eq 0 ]]; then
    found_matches="$(matching_processes "$process_pattern")"
    if [[ -z "$found_matches" ]]; then
      rm -f "$PID_FILE" "$META_FILE"
      echo "No running load workers found."
      return
    fi
  fi

  while (( attempt < max_attempts )); do
    attempt=$((attempt + 1))

    if have_command pkill; then
      pkill -f "$HARD_STOP_PATTERN" >/dev/null 2>&1 || true
    fi

    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      if kill -0 "$pid" >/dev/null 2>&1; then
        had_matches=true
        kill "$pid" >/dev/null 2>&1 || true
      fi
    done < <(alive_pids || true)

    found_matches="$(matching_processes "$process_pattern")"
    if [[ -n "$found_matches" ]]; then
      had_matches=true
      if have_command pkill; then
        pkill -f "$process_pattern" >/dev/null 2>&1 || true
      fi
    fi

    sleep 1

    if have_command pkill; then
      pkill -9 -f "$HARD_STOP_PATTERN" >/dev/null 2>&1 || true
    fi

    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      if kill -0 "$pid" >/dev/null 2>&1; then
        had_matches=true
        kill -9 "$pid" >/dev/null 2>&1 || true
      fi
    done < <(alive_pids || true)

    found_matches="$(matching_processes "$process_pattern")"
    if [[ -n "$found_matches" ]]; then
      had_matches=true
      if have_command pkill; then
        pkill -9 -f "$process_pattern" >/dev/null 2>&1 || true
      fi
    fi

    sleep 1

    found_matches="$(matching_processes "$process_pattern")"
    alive=()
    while IFS= read -r pid; do
      [[ -n "$pid" ]] && alive+=("$pid")
    done < <(alive_pids || true)

    if [[ ${#alive[@]} -eq 0 && -z "$found_matches" ]]; then
      rm -f "$PID_FILE" "$META_FILE"
      if [[ "$had_matches" == true ]]; then
        echo "Stopped all matching load processes."
      else
        echo "No running load workers found."
      fi
      return
    fi
  done

  rm -f "$PID_FILE" "$META_FILE"

  echo "Some matching load processes may still be running after ${max_attempts} stop attempts." >&2
  echo "Process pattern used: ${process_pattern}" >&2
  found_matches="$(matching_processes "$process_pattern")"
  if [[ -n "$found_matches" ]]; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && echo "$line" >&2
    done <<<"$found_matches"
  fi
}

status_load() {
  local alive=()
  local external_matches=""
  local process_pattern=""
  local request_url=""

  while IFS= read -r pid; do
    [[ -n "$pid" ]] && alive+=("$pid")
  done < <(alive_pids || true)

  request_url="$(read_meta_value "REQUEST_URL")"
  process_pattern="$(build_process_pattern "$request_url" "$DEFAULT_TARGET_BASE")"
  external_matches="$(matching_processes "$process_pattern")"

  if [[ ${#alive[@]} -eq 0 && -z "$external_matches" ]]; then
    rm -f "$PID_FILE" "$META_FILE"
    echo "No running load workers found."
    return
  fi

  if [[ ${#alive[@]} -gt 0 ]]; then
    echo "Load test status: running (${#alive[@]} tracked workers, sustained)"
    echo "Tracked PIDs: ${alive[*]}"
  else
    echo "Load test status: external matching traffic still detected"
  fi

  if [[ -f "$META_FILE" ]]; then
    cat "$META_FILE"
  fi
  if [[ -n "$external_matches" ]]; then
    echo "Matching processes:"
    printf '%s\n' "$external_matches"
  fi
  echo "Log: ${LOG_FILE}"
}

burst_load() {
  local count="${1:-30}"
  local iterations="${2:-2500000}"
  local target_base="${3:-$DEFAULT_TARGET_BASE}"
  local request_url

  require_remote_target "$target_base"

  request_url="$(append_iterations "$target_base" "$iterations")"

  echo "Running burst: ${count} requests"
  echo "Target: ${request_url}"

  for _ in $(seq 1 "$count"); do
    curl -s --fail --max-time 120 "$request_url" >/dev/null &
  done
  wait

  echo "Burst complete."
}

main() {
  require_command curl
  require_command /bin/bash

  local action="${1:-help}"

  case "$action" in
    start)
      start_load "${2:-scaleout70}" "${3:-$DEFAULT_TARGET_BASE}"
      ;;
    probe)
      probe_target "${2:-scaleout70}" "${3:-$DEFAULT_TARGET_BASE}"
      ;;
    stop)
      stop_load
      ;;
    restart)
      stop_load
      start_load "${2:-scaleout70}" "${3:-$DEFAULT_TARGET_BASE}"
      ;;
    status)
      status_load
      ;;
    burst)
      burst_load "${2:-30}" "${3:-2500000}" "${4:-$DEFAULT_TARGET_BASE}"
      ;;
    help|-h|--help)
      usage
      ;;
    *)
      echo "Unknown action: $action" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
