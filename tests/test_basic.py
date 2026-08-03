import tempfile
from pathlib import Path

from config import AppConfig, _env_bool, _env_float, _env_int
from metrics_logger import MetricsLogger
from monitor import MonitoringService
from runtime_guard import enforce_local_dashboard_runtime
from scaler import ScalingController


class FakeAWSClient:
    def __init__(self):
        self.calls = []
        self.asg_updates = []

    def set_desired_capacity(self, desired_capacity, asg_name=None, honor_cooldown=False):
        self.calls.append(
            {
                "desired_capacity": desired_capacity,
                "asg_name": asg_name,
                "honor_cooldown": honor_cooldown,
            }
        )
        return {"status": "submitted", "desired_capacity": desired_capacity}

    def get_ec2_instances(self):
        return [
            {
                "instance_id": "i-123",
                "state": "running",
                "instance_type": "t3.micro",
                "private_ip": "10.0.0.10",
                "public_ip": None,
                "launch_time": "2025-01-01T00:00:00+00:00",
                "availability_zone": "us-east-1a",
                "tags": {"Name": "demo"},
                "health_status": "unknown",
                "lifecycle_state": "standalone",
                "protected_from_scale_in": False,
            }
        ]

    def get_asg_details(self):
        return {
            "name": "demo-asg",
            "min_size": 2,
            "max_size": 5,
            "desired_capacity": 2,
            "default_cooldown": 30,
            "instances": [
                {
                    "instance_id": "i-123",
                    "health_status": "Healthy",
                    "lifecycle_state": "InService",
                    "protected_from_scale_in": False,
                }
            ],
        }

    def get_instance_cpu_metrics(self, instance_ids):
        return {
            "i-123": [
                {"timestamp": "2025-01-01T00:00:00+00:00", "value": 45.0},
                {"timestamp": "2025-01-01T00:01:00+00:00", "value": 55.0},
            ]
        }

    def get_alb_request_series(self):
        return [{"timestamp": "2025-01-01T00:01:00+00:00", "value": 120.0}]

    def get_alb_target_health_series(self):
        return [{"timestamp": "2025-01-01T00:02:00+00:00", "value": 2.0}]

    def get_target_group_health(self):
        return {
            "configured": True,
            "target_group_arn": "arn:demo:target-group",
            "target_group_name": "demo-target-group",
            "protocol": "HTTP",
            "port": 5000,
            "health_check_path": "/healthz",
            "counts": {
                "healthy": 1,
                "unhealthy": 1,
                "initial": 0,
                "total": 2,
            },
            "targets": [
                {
                    "id": "i-123",
                    "port": 5000,
                    "state": "healthy",
                    "reason": None,
                    "description": None,
                },
                {
                    "id": "i-456",
                    "port": 5000,
                    "state": "unhealthy",
                    "reason": "Target.Timeout",
                    "description": "Request timed out",
                },
            ],
        }

    def get_recent_scaling_activities(self, max_records=20):
        return []

    def update_auto_scaling_group(
        self,
        min_size=None,
        max_size=None,
        default_cooldown=None,
        desired_capacity=None,
        asg_name=None,
    ):
        self.asg_updates.append(
            {
                "min_size": min_size,
                "max_size": max_size,
                "default_cooldown": default_cooldown,
                "desired_capacity": desired_capacity,
                "asg_name": asg_name,
            }
        )
        return {
            "status": "updated",
            "asg_name": asg_name or "demo-asg",
            "min_size": min_size,
            "max_size": max_size,
            "default_cooldown": default_cooldown,
            "desired_capacity": desired_capacity,
        }


def build_config(tmp_dir: Path) -> AppConfig:
    return AppConfig(
        base_dir=tmp_dir,
        flask_env="testing",
        app_host="127.0.0.1",
        app_port=5000,
        dashboard_runtime_policy="local_only",
        allow_dashboard_on_aws=False,
        local_demo_work_enabled=False,
        aws_region="us-east-1",
        aws_profile=None,
        use_iam_role=True,
        monitoring_label="test",
        ec2_tag_key=None,
        ec2_tag_value=None,
        auto_scaling_group_name="demo-asg",
        load_balancer_arn=None,
        target_group_arn=None,
        metric_window_minutes=60,
        metric_period_seconds=60,
        poll_interval_seconds=30,
        scaling_mode="custom",
        scale_out_cpu_threshold=70.0,
        scale_in_cpu_threshold=30.0,
        scaler_scale_out_confirmation_samples=1,
        scaler_scale_in_confirmation_samples=1,
        scaler_request_signal_threshold=3.0,
        scaler_scale_out_request_signal_threshold=1.0,
        scaler_fast_scale_out_step=2,
        scaler_fast_scale_out_cpu_ratio=1.05,
        scaler_fast_scale_in_step=2,
        scaler_fast_scale_in_cpu_ratio=0.5,
        scaler_idle_collapse_cpu_ratio=0.8,
        scaler_min_instances=1,
        scaler_max_instances=4,
        scaler_hard_min_instances=1,
        scaler_hard_max_instances=10,
        scaler_cooldown_seconds=60,
        control_enabled=True,
        control_api_token=None,
        control_allow_force=True,
        log_to_s3=False,
        s3_log_bucket=None,
        metrics_csv_path=tmp_dir / "data/metrics.csv",
        events_csv_path=tmp_dir / "data/events.csv",
        sqlite_path=tmp_dir / "data/metrics.db",
        controller_state_path=tmp_dir / "data/controller_state.json",
        demo_work_max_iterations=1000,
    )


def test_metrics_logger_writes_metric_and_event():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        logger = MetricsLogger(config=config, aws_client=None)

        logger.log_metric(
            {
                "timestamp": "2025-01-01T00:00:00+00:00",
                "average_cpu": 48.5,
                "instance_count": 2,
                "request_count": 120.0,
                "healthy_host_count": 2,
                "desired_capacity": 2,
                "mode": "custom",
                "scale_out_cpu_threshold": 70,
                "scale_in_cpu_threshold": 30,
                "min_instances": 1,
                "max_instances": 4,
                "cooldown_seconds": 300,
                "scaling_action": "none",
                "load_balancer_arn": "",
                "auto_scaling_group_name": "demo-asg",
            }
        )
        logger.log_event(
            {
                "timestamp": "2025-01-01T00:01:00+00:00",
                "event_source": "controller",
                "event_type": "scaling_decision",
                "action": "scale_out",
                "message": "CPU above threshold",
                "mode": "custom",
                "desired_capacity": 3,
                "result": "submitted",
                "details": "{}",
            }
        )

        metrics = logger.get_recent_metrics(limit=10)
        events = logger.get_recent_events(limit=10)

        assert len(metrics) == 1
        assert metrics[0]["instance_count"] == 2
        assert len(events) == 1
        assert events[0]["action"] == "scale_out"


def test_env_helpers_fall_back_on_invalid_values(monkeypatch):
    monkeypatch.setenv("BAD_BOOL", "sometimes")
    monkeypatch.setenv("BAD_INT", "ten")
    monkeypatch.setenv("BAD_FLOAT", "high")

    assert _env_bool("BAD_BOOL", True) is True
    assert _env_int("BAD_INT", 10) == 10
    assert _env_float("BAD_FLOAT", 2.5) == 2.5


def test_runtime_guard_allows_local_dashboard_runtime():
    status = enforce_local_dashboard_runtime(
        "local_only",
        allow_dashboard_on_aws=False,
        env={},
        metadata_probe=lambda: False,
    )

    assert status["status"] == "local"
    assert status["deployment_model"] == "local-dashboard-remote-aws-resources"


def test_runtime_guard_blocks_aws_dashboard_runtime_without_override():
    try:
        enforce_local_dashboard_runtime(
            "local_only",
            allow_dashboard_on_aws=False,
            env={"AWS_EXECUTION_ENV": "AWS_ECS_FARGATE"},
            metadata_probe=lambda: False,
        )
    except RuntimeError as exc:
        assert "Run this monitoring dashboard on the operator Mac" in str(exc)
    else:
        raise AssertionError("Expected local-only runtime guard to block AWS runtime")


def test_scaler_submits_scale_out_when_cpu_exceeds_threshold():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 91.0,
                "desired_capacity": 2,
                "instance_count": 2,
                "request_count": 25.0,
            },
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "value": 82.0},
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 91.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 25.0},
                ],
            }
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "submitted"
        assert result["action"] == "scale_out"
        assert fake_aws.calls[-1]["desired_capacity"] == 4


def test_scaler_scale_out_uses_single_sample_when_request_signal_is_present():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 78.0,
                "desired_capacity": 2,
                "instance_count": 2,
                "request_count": 8.0,
            },
            "asg": fake_aws.get_asg_details(),
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 78.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 8.0},
                ],
            },
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "submitted"
        assert result["action"] == "scale_out"
        assert result["desired_capacity"] == 4
        assert fake_aws.calls[-1]["desired_capacity"] == 4


def test_scaler_scale_out_uses_fast_step_for_very_high_cpu_demo_spike():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 98.0,
                "desired_capacity": 2,
                "instance_count": 2,
                "request_count": 0.0,
            },
            "asg": fake_aws.get_asg_details(),
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 98.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 0.0},
                ],
            },
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "submitted"
        assert result["action"] == "scale_out"
        assert result["desired_capacity"] == 4
        assert "add 2 instances" in result["reason"]
        assert fake_aws.calls[-1]["desired_capacity"] == 4


def test_monitoring_snapshot_prefers_direct_target_health_and_builds_warning():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        service = MonitoringService(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = service.collect_snapshot()

        assert snapshot["summary"]["healthy_host_count"] == 1
        assert snapshot["target_health"]["counts"]["unhealthy"] == 1
        assert any("Target.Timeout" in warning for warning in snapshot["warnings"])


def test_scaler_waits_while_capacity_is_still_converging():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 95.0,
                "desired_capacity": 1,
                "instance_count": 3,
                "request_count": 40.0,
            },
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "value": 88.0},
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 95.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 40.0},
                ],
            },
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "noop"
        assert "converging" in result["reason"]
        assert fake_aws.calls == []


def test_scaler_ignores_unconfirmed_high_cpu_spike_without_request_signal():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 72.0,
                "desired_capacity": 2,
                "instance_count": 2,
                "request_count": 0.0,
            },
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "value": 42.0},
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 72.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 0.0},
                ],
            },
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "noop"
        assert "not confirmed" in result["reason"]
        assert fake_aws.calls == []


def test_scaler_does_not_process_the_same_cpu_sample_twice():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 91.0,
                "desired_capacity": 2,
                "instance_count": 2,
                "request_count": 25.0,
            },
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "value": 82.0},
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 91.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 25.0},
                ],
            },
        }

        first_result = controller.evaluate(snapshot, source="automatic")
        second_result = controller.evaluate(snapshot, source="automatic")

        assert first_result["status"] == "submitted"
        assert second_result["status"] == "noop"
        assert "already evaluated" in second_result["reason"]
        assert len(fake_aws.calls) == 1


def test_scaler_does_not_scale_in_while_requests_are_still_present():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 12.0,
                "desired_capacity": 3,
                "instance_count": 3,
                "request_count": 5.0,
            },
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "value": 15.0},
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 12.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 5.0},
                ],
            },
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "noop"
        assert "request activity is still present" in result["reason"]
        assert fake_aws.calls == []


def test_scaler_demo_fast_scale_in_uses_idle_step_down():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 5.0,
                "desired_capacity": 4,
                "instance_count": 4,
                "request_count": 1.0,
            },
            "asg": {
                **fake_aws.get_asg_details(),
                "desired_capacity": 4,
                "min_size": 2,
            },
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "value": 11.0},
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 5.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 1.0},
                ],
            },
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "submitted"
        assert result["action"] == "scale_in"
        assert result["desired_capacity"] == 2
        assert "reduce capacity by 2 instances" in result["reason"]
        assert fake_aws.calls[-1]["desired_capacity"] == 2


def test_scaler_idle_collapse_can_drop_directly_to_min_for_demo():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 20.0,
                "desired_capacity": 5,
                "instance_count": 5,
                "request_count": 0.0,
            },
            "asg": {
                **fake_aws.get_asg_details(),
                "desired_capacity": 5,
                "min_size": 2,
                "max_size": 6,
            },
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "value": 23.0},
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 20.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "value": 0.0},
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 0.0},
                ],
            },
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "submitted"
        assert result["action"] == "scale_in"
        assert result["desired_capacity"] == 2
        assert fake_aws.calls[-1]["desired_capacity"] == 2


def test_scaler_scale_in_accepts_single_low_cpu_sample_for_demo_speed():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 22.0,
                "desired_capacity": 3,
                "instance_count": 3,
                "request_count": 0.0,
            },
            "asg": {
                **fake_aws.get_asg_details(),
                "desired_capacity": 3,
                "min_size": 2,
            },
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 22.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 0.0},
                ],
            },
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "submitted"
        assert result["action"] == "scale_in"
        assert result["desired_capacity"] == 2
        assert fake_aws.calls[-1]["desired_capacity"] == 2


def test_scaler_parses_string_false_for_active_control():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        result = controller.update_settings({"active_control": "false"})

        assert result["status"] == "updated"
        assert controller.get_state()["active_control"] is False


def test_scaler_syncs_asg_bounds_when_settings_change():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        result = controller.update_settings(
            {
                "min_instances": 2,
                "max_instances": 3,
                "cooldown_seconds": 180,
            }
        )

        assert result["status"] == "updated"
        assert result["aws_sync"]["status"] == "updated"
        assert fake_aws.asg_updates[-1]["min_size"] == 2
        assert fake_aws.asg_updates[-1]["max_size"] == 3
        assert fake_aws.asg_updates[-1]["default_cooldown"] == 180
        assert controller.get_state()["min_instances"] == 2
        assert controller.get_state()["max_instances"] == 3


def test_monitoring_service_includes_healthy_host_metrics_in_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        service = MonitoringService(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = service.collect_snapshot()

        assert snapshot["summary"]["healthy_host_count"] == 1
        assert snapshot["raw_series"]["healthy_host_count"][-1]["value"] == 2.0
        assert snapshot["collected_at"] == "2025-01-01T00:02:00+00:00"


def test_scaler_reconciles_local_bounds_with_live_asg_before_scale_in():
    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FakeAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 5.0,
                "desired_capacity": 2,
                "instance_count": 2,
                "request_count": 0.0,
            },
            "asg": fake_aws.get_asg_details(),
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "value": 5.0},
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 5.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 0.0},
                ],
            },
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "noop"
        assert fake_aws.calls == []
        assert controller.get_state()["min_instances"] == 2
        assert controller.get_state()["max_instances"] == 5
        assert controller.get_state()["cooldown_seconds"] == 30


def test_scaler_returns_error_response_when_aws_rejects_scaling_request():
    class FailingAWSClient(FakeAWSClient):
        def set_desired_capacity(self, desired_capacity, asg_name=None, honor_cooldown=False):
            raise RuntimeError("validation failed")

    with tempfile.TemporaryDirectory() as tmp:
        config = build_config(Path(tmp))
        config.ensure_runtime_dirs()
        fake_aws = FailingAWSClient()
        logger = MetricsLogger(config=config, aws_client=None)
        controller = ScalingController(config=config, aws_client=fake_aws, metrics_logger=logger)

        snapshot = {
            "summary": {
                "average_cpu": 91.0,
                "desired_capacity": 2,
                "instance_count": 2,
                "request_count": 25.0,
            },
            "asg": fake_aws.get_asg_details(),
            "raw_series": {
                "cpu": [
                    {"timestamp": "2025-01-01T00:00:00+00:00", "value": 82.0},
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 91.0},
                ],
                "request_count": [
                    {"timestamp": "2025-01-01T00:01:00+00:00", "value": 25.0},
                ],
            },
        }

        result = controller.evaluate(snapshot, source="automatic")

        assert result["status"] == "error"
        assert result["action"] == "scale_out"
        assert "validation failed" in result["reason"]
