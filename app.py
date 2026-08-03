import logging
import math
import time
from threading import Lock
from typing import Any, Dict

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from flask import Flask, jsonify, render_template, request, send_file

from aws_client import AWSClient
from config import CONFIG
from metrics_logger import MetricsLogger
from monitor import MonitoringService
from runtime_guard import enforce_local_dashboard_runtime
from scaler import ScalingController


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = Flask(__name__)
RUNTIME_STATUS = enforce_local_dashboard_runtime(
    CONFIG.dashboard_runtime_policy,
    CONFIG.allow_dashboard_on_aws,
)
aws_client = AWSClient(CONFIG)
metrics_logger = MetricsLogger(CONFIG, aws_client=aws_client)
monitoring_service = MonitoringService(CONFIG, aws_client, metrics_logger)
scaling_controller = ScalingController(CONFIG, aws_client, metrics_logger)
snapshot_cache_lock = Lock()
snapshot_cache: Dict[str, Any] = {
    "payload": None,
    "loaded_at": 0.0,
}
SNAPSHOT_CACHE_TTL_SECONDS = 10


def _error_response(message: str, status_code: int = 400):
    return jsonify({"error": message}), status_code


def _parse_bool_arg(name: str, default: bool = False) -> bool:
    raw_value = request.args.get(name)
    if raw_value is None:
        return default

    normalised = raw_value.strip().lower()
    if normalised in {"1", "true", "yes", "on"}:
        return True
    if normalised in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


def _parse_bounded_int_arg(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = request.args.get(name)
    if raw_value in (None, ""):
        return default

    value = int(raw_value)
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return min(value, maximum)


def _validate_control_token(payload: Dict[str, Any]) -> None:
    if not CONFIG.token_required:
        return

    supplied_token = request.headers.get("X-Control-Token") or payload.get("control_token")
    if supplied_token != CONFIG.control_api_token:
        raise PermissionError("Invalid or missing control token.")


def _load_snapshot(run_controller: bool = True) -> Dict[str, Any]:
    snapshot = monitoring_service.collect_snapshot()
    controller_result = (
        scaling_controller.evaluate(snapshot, source="automatic")
        if run_controller
        else {"status": "noop", "action": "none", "reason": "Controller evaluation skipped."}
    )
    controller_state = scaling_controller.get_state()
    monitoring_service.log_snapshot(snapshot, controller_state, controller_result)

    return {
        **snapshot,
        "controller_state": controller_state,
        "controller_result": controller_result,
        "history": monitoring_service.get_history(limit=120),
        "events": monitoring_service.get_events(limit=50),
    }


def _get_cached_snapshot(force_refresh: bool = False) -> Dict[str, Any]:
    with snapshot_cache_lock:
        now = time.time()
        cached_payload = snapshot_cache.get("payload")
        cached_loaded_at = float(snapshot_cache.get("loaded_at") or 0.0)
        if (
            not force_refresh
            and cached_payload is not None
            and (now - cached_loaded_at) < SNAPSHOT_CACHE_TTL_SECONDS
        ):
            return cached_payload

        payload = _load_snapshot(run_controller=True)
        snapshot_cache["payload"] = payload
        snapshot_cache["loaded_at"] = time.time()
        return payload


def _invalidate_snapshot_cache() -> None:
    with snapshot_cache_lock:
        snapshot_cache["payload"] = None
        snapshot_cache["loaded_at"] = 0.0


@app.route("/")
def index():
    return render_template(
        "index.html",
        monitoring_label=CONFIG.monitoring_label,
        poll_interval_seconds=CONFIG.poll_interval_seconds,
        scaling_mode=CONFIG.scaling_mode,
    )


@app.route("/control")
def control_page():
    return render_template(
        "control.html",
        monitoring_label=CONFIG.monitoring_label,
        poll_interval_seconds=CONFIG.poll_interval_seconds,
        token_required=CONFIG.token_required,
        control_allow_force=CONFIG.control_allow_force,
    )


@app.route("/healthz")
def healthcheck():
    return jsonify(
        {
            "status": "ok",
            "service": "aws-autoscaling-dashboard",
            "runtime": RUNTIME_STATUS,
        }
    )


@app.route("/demo/work")
def demo_work():
    if not CONFIG.local_demo_work_enabled:
        return _error_response(
            "Local dashboard /demo/work is disabled. Generate load against the "
            "AWS ALB /demo/work endpoint configured by Terraform and Ansible.",
            403,
        )

    try:
        iterations = _parse_bounded_int_arg(
            "iterations",
            default=250000,
            minimum=1,
            maximum=CONFIG.demo_work_max_iterations,
        )
    except ValueError as exc:
        return _error_response(str(exc), 400)

    started = time.perf_counter()
    accumulator = 0.0
    for index in range(iterations):
        accumulator += math.sqrt(index + 1)
    elapsed = round(time.perf_counter() - started, 4)
    return jsonify(
        {
            "status": "ok",
            "iterations": iterations,
            "elapsed_seconds": elapsed,
            "checksum": round(accumulator, 2),
        }
    )


@app.route("/api/metrics")
def api_metrics():
    try:
        force_refresh = _parse_bool_arg("refresh", default=False)
        payload = _get_cached_snapshot(force_refresh=force_refresh)
        return jsonify(payload)
    except ValueError as exc:
        return _error_response(str(exc), 400)
    except NoCredentialsError:
        return _error_response(
            "AWS credentials were not found. Fill lab.env with current Canvas credentials, run ./scripts/sync_dashboard_env.sh, then restart the dashboard.",
            500,
        )
    except (ClientError, BotoCoreError) as exc:
        return _error_response(f"AWS API call failed: {exc}", 500)
    except Exception as exc:  # pylint: disable=broad-except
        logging.exception("Unexpected metrics error")
        return _error_response(str(exc), 500)


@app.route("/api/instances")
def api_instances():
    try:
        snapshot = monitoring_service.collect_snapshot()
        return jsonify({"instances": snapshot["instances"], "asg": snapshot["asg"]})
    except Exception as exc:  # pylint: disable=broad-except
        return _error_response(str(exc), 500)


@app.route("/api/events")
def api_events():
    try:
        limit = _parse_bounded_int_arg("limit", default=50, minimum=1, maximum=200)
        return jsonify({"events": monitoring_service.get_events(limit=limit)})
    except ValueError as exc:
        return _error_response(str(exc), 400)


@app.route("/api/history")
def api_history():
    try:
        limit = _parse_bounded_int_arg("limit", default=120, minimum=1, maximum=500)
        return jsonify({"history": monitoring_service.get_history(limit=limit)})
    except ValueError as exc:
        return _error_response(str(exc), 400)


@app.route("/api/control", methods=["GET", "POST"])
def api_control():
    if request.method == "GET":
        return jsonify(
            {
                "controller_state": scaling_controller.get_state(),
                "limits": {
                    "hard_min_instances": CONFIG.scaler_hard_min_instances,
                    "hard_max_instances": CONFIG.scaler_hard_max_instances,
                },
                "control_enabled": CONFIG.control_enabled,
                "token_required": CONFIG.token_required,
                "control_allow_force": CONFIG.control_allow_force,
            }
        )

    payload = request.get_json(silent=True) or request.form.to_dict()
    try:
        _validate_control_token(payload)
        snapshot = monitoring_service.collect_snapshot()
        action_result = scaling_controller.apply_control_action(payload, snapshot=snapshot)
        monitoring_service.log_snapshot(snapshot, scaling_controller.get_state(), action_result)
        _invalidate_snapshot_cache()
        return jsonify(
            {
                "result": action_result,
                "controller_state": scaling_controller.get_state(),
                "history": monitoring_service.get_history(limit=30),
                "events": monitoring_service.get_events(limit=20),
                "limits": {
                    "hard_min_instances": CONFIG.scaler_hard_min_instances,
                    "hard_max_instances": CONFIG.scaler_hard_max_instances,
                },
                "control_enabled": CONFIG.control_enabled,
                "token_required": CONFIG.token_required,
                "control_allow_force": CONFIG.control_allow_force,
            }
        )
    except PermissionError as exc:
        return _error_response(str(exc), 403)
    except ValueError as exc:
        return _error_response(str(exc), 400)
    except Exception as exc:  # pylint: disable=broad-except
        logging.exception("Control API error")
        return _error_response(str(exc), 500)


@app.route("/api/download-metrics")
def api_download_metrics():
    if not CONFIG.metrics_csv_path.exists():
        return _error_response("metrics.csv does not exist yet.", 404)
    return send_file(
        CONFIG.metrics_csv_path,
        as_attachment=True,
        download_name="metrics.csv",
        mimetype="text/csv",
    )


if __name__ == "__main__":
    app.run(
        host=CONFIG.app_host,
        port=CONFIG.app_port,
        debug=CONFIG.flask_env == "development",
    )
