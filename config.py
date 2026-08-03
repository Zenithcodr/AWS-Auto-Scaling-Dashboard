import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# botocore treats an empty AWS_PROFILE/AWS_DEFAULT_PROFILE as a real profile name.
# Clear blank values so temporary env-credential setups work cleanly.
for profile_var in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
    if os.getenv(profile_var, "").strip() == "":
        os.environ.pop(profile_var, None)

SUPPORTED_SCALING_MODES = ("custom", "aws_managed")


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value in (None, ""):
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def _resolve_path(path_value: str, base_dir: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


@dataclass
class AppConfig:
    base_dir: Path
    flask_env: str
    app_host: str
    app_port: int
    dashboard_runtime_policy: str
    allow_dashboard_on_aws: bool
    local_demo_work_enabled: bool
    aws_region: str
    aws_profile: Optional[str]
    use_iam_role: bool
    monitoring_label: str
    ec2_tag_key: Optional[str]
    ec2_tag_value: Optional[str]
    auto_scaling_group_name: Optional[str]
    load_balancer_arn: Optional[str]
    target_group_arn: Optional[str]
    metric_window_minutes: int
    metric_period_seconds: int
    poll_interval_seconds: int
    scaling_mode: str
    scale_out_cpu_threshold: float
    scale_in_cpu_threshold: float
    scaler_scale_out_confirmation_samples: int
    scaler_scale_in_confirmation_samples: int
    scaler_request_signal_threshold: float
    scaler_scale_out_request_signal_threshold: float
    scaler_fast_scale_out_step: int
    scaler_fast_scale_out_cpu_ratio: float
    scaler_fast_scale_in_step: int
    scaler_fast_scale_in_cpu_ratio: float
    scaler_idle_collapse_cpu_ratio: float
    scaler_min_instances: int
    scaler_max_instances: int
    scaler_hard_min_instances: int
    scaler_hard_max_instances: int
    scaler_cooldown_seconds: int
    control_enabled: bool
    control_api_token: Optional[str]
    control_allow_force: bool
    log_to_s3: bool
    s3_log_bucket: Optional[str]
    metrics_csv_path: Path
    events_csv_path: Path
    sqlite_path: Path
    controller_state_path: Path
    demo_work_max_iterations: int

    @classmethod
    def from_env(cls) -> "AppConfig":
        scaling_mode = os.getenv("SCALING_MODE", "custom").strip().lower()
        if scaling_mode not in SUPPORTED_SCALING_MODES:
            scaling_mode = "custom"

        return cls(
            base_dir=BASE_DIR,
            flask_env=os.getenv("FLASK_ENV", "production"),
            app_host=os.getenv("APP_HOST", "0.0.0.0"),
            app_port=_env_int("APP_PORT", 5000),
            dashboard_runtime_policy=os.getenv("DASHBOARD_RUNTIME_POLICY", "local_only"),
            allow_dashboard_on_aws=_env_bool("ALLOW_DASHBOARD_ON_AWS", False),
            local_demo_work_enabled=_env_bool("LOCAL_DEMO_WORK_ENABLED", False),
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
            aws_profile=os.getenv("AWS_PROFILE") or None,
            use_iam_role=_env_bool("USE_IAM_ROLE", False),
            monitoring_label=os.getenv(
                "MONITORING_LABEL",
                "AWS Auto-Scaling Monitoring & Control Dashboard",
            ),
            ec2_tag_key=os.getenv("EC2_TAG_KEY") or None,
            ec2_tag_value=os.getenv("EC2_TAG_VALUE") or None,
            auto_scaling_group_name=os.getenv("AUTO_SCALING_GROUP_NAME") or None,
            load_balancer_arn=os.getenv("LOAD_BALANCER_ARN") or None,
            target_group_arn=os.getenv("TARGET_GROUP_ARN") or None,
            metric_window_minutes=_env_int("AWS_METRIC_WINDOW_MINUTES", 60),
            metric_period_seconds=_env_int("AWS_METRIC_PERIOD_SECONDS", 60),
            poll_interval_seconds=_env_int("POLL_INTERVAL_SECONDS", 10),
            scaling_mode=scaling_mode,
            scale_out_cpu_threshold=_env_float("SCALE_OUT_CPU_THRESHOLD", 70.0),
            scale_in_cpu_threshold=_env_float("SCALE_IN_CPU_THRESHOLD", 30.0),
            scaler_scale_out_confirmation_samples=_env_int(
                "SCALER_SCALE_OUT_CONFIRMATION_SAMPLES",
                1,
            ),
            scaler_scale_in_confirmation_samples=_env_int(
                "SCALER_SCALE_IN_CONFIRMATION_SAMPLES",
                1,
            ),
            scaler_request_signal_threshold=_env_float("SCALER_REQUEST_SIGNAL_THRESHOLD", 3.0),
            scaler_scale_out_request_signal_threshold=_env_float(
                "SCALER_SCALE_OUT_REQUEST_SIGNAL_THRESHOLD",
                1.0,
            ),
            scaler_fast_scale_out_step=_env_int("SCALER_FAST_SCALE_OUT_STEP", 2),
            scaler_fast_scale_out_cpu_ratio=_env_float("SCALER_FAST_SCALE_OUT_CPU_RATIO", 1.05),
            scaler_fast_scale_in_step=_env_int("SCALER_FAST_SCALE_IN_STEP", 2),
            scaler_fast_scale_in_cpu_ratio=_env_float("SCALER_FAST_SCALE_IN_CPU_RATIO", 0.5),
            scaler_idle_collapse_cpu_ratio=_env_float("SCALER_IDLE_COLLAPSE_CPU_RATIO", 0.8),
            scaler_min_instances=_env_int("SCALER_MIN_INSTANCES", 1),
            scaler_max_instances=_env_int("SCALER_MAX_INSTANCES", 4),
            scaler_hard_min_instances=_env_int("SCALER_HARD_MIN_INSTANCES", 1),
            scaler_hard_max_instances=_env_int("SCALER_HARD_MAX_INSTANCES", 10),
            scaler_cooldown_seconds=_env_int("SCALER_COOLDOWN_SECONDS", 60),
            control_enabled=_env_bool("CONTROL_ENABLED", True),
            control_api_token=os.getenv("CONTROL_API_TOKEN") or None,
            control_allow_force=_env_bool("CONTROL_ALLOW_FORCE", True),
            log_to_s3=_env_bool("LOG_TO_S3", False),
            s3_log_bucket=os.getenv("S3_LOG_BUCKET") or None,
            metrics_csv_path=_resolve_path(os.getenv("METRICS_CSV_PATH", "data/metrics.csv"), BASE_DIR),
            events_csv_path=_resolve_path(os.getenv("EVENTS_CSV_PATH", "data/events.csv"), BASE_DIR),
            sqlite_path=_resolve_path(os.getenv("SQLITE_PATH", "data/metrics.db"), BASE_DIR),
            controller_state_path=_resolve_path(
                os.getenv("CONTROLLER_STATE_PATH", "data/controller_state.json"),
                BASE_DIR,
            ),
            demo_work_max_iterations=_env_int("DEMO_WORK_MAX_ITERATIONS", 8000000),
        )

    def ensure_runtime_dirs(self) -> None:
        runtime_paths = [
            self.metrics_csv_path,
            self.events_csv_path,
            self.sqlite_path,
            self.controller_state_path,
        ]
        for path in runtime_paths:
            path.parent.mkdir(parents=True, exist_ok=True)

    def boto3_session_kwargs(self) -> Dict[str, str]:
        kwargs: Dict[str, str] = {"region_name": self.aws_region}
        if self.aws_profile:
            kwargs["profile_name"] = self.aws_profile
        return kwargs

    @property
    def token_required(self) -> bool:
        return bool(self.control_api_token)


CONFIG = AppConfig.from_env()
CONFIG.ensure_runtime_dirs()
