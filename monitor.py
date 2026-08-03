from collections import defaultdict
from typing import Any, Dict, List

from aws_client import AWSClient
from config import AppConfig
from metrics_logger import MetricsLogger


class MonitoringService:
    def __init__(self, config: AppConfig, aws_client: AWSClient, metrics_logger: MetricsLogger):
        self.config = config
        self.aws_client = aws_client
        self.metrics_logger = metrics_logger

    def collect_snapshot(self) -> Dict[str, Any]:
        instances = self.aws_client.get_ec2_instances()
        asg = self.aws_client.get_asg_details()
        merged_instances = self._merge_asg_metadata(instances, asg)

        active_instances = [
            instance for instance in merged_instances if instance["state"] in {"running", "pending"}
        ]
        instance_ids = [instance["instance_id"] for instance in active_instances]

        cpu_series_by_instance = self.aws_client.get_instance_cpu_metrics(instance_ids)
        average_cpu_series = self._aggregate_series(cpu_series_by_instance)
        request_series = self.aws_client.get_alb_request_series()
        healthy_host_series = self.aws_client.get_alb_target_health_series()
        target_health = self.aws_client.get_target_group_health()
        desired_capacity = asg.get("desired_capacity") if asg else len(active_instances)
        target_health_counts = target_health.get("counts", {}) if target_health else {}
        direct_healthy_hosts = target_health_counts.get("healthy")
        healthy_host_count = (
            direct_healthy_hosts
            if direct_healthy_hosts is not None
            else self._latest_value(healthy_host_series)
        )

        return {
            "collected_at": self._latest_timestamp(
                average_cpu_series,
                request_series,
                healthy_host_series,
            ),
            "summary": {
                "average_cpu": self._latest_value(average_cpu_series),
                "instance_count": len(active_instances),
                "request_count": self._latest_value(request_series),
                "healthy_host_count": healthy_host_count,
                "desired_capacity": desired_capacity,
                "operating_mode": "custom" if self.config.scaling_mode == "custom" else "aws_managed",
            },
            "raw_series": {
                "cpu": average_cpu_series,
                "request_count": request_series,
                "healthy_host_count": healthy_host_series,
                "desired_capacity": self._build_flat_series(
                    average_cpu_series,
                    desired_capacity,
                    request_series,
                ),
            },
            "instances": merged_instances,
            "asg": asg or {},
            "target_health": target_health,
            "warnings": self._build_warnings(
                target_health=target_health,
                desired_capacity=desired_capacity,
                active_instance_count=len(active_instances),
            ),
        }

    def log_snapshot(
        self,
        snapshot: Dict[str, Any],
        controller_state: Dict[str, Any],
        controller_result: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        summary = snapshot["summary"]
        scaling_action = "none"
        if controller_result and controller_result.get("status") == "submitted":
            scaling_action = controller_result.get("action") or "none"

        return self.metrics_logger.log_metric(
            {
                "timestamp": snapshot.get("collected_at"),
                "average_cpu": summary.get("average_cpu"),
                "instance_count": summary.get("instance_count"),
                "request_count": summary.get("request_count"),
                "healthy_host_count": summary.get("healthy_host_count"),
                "desired_capacity": summary.get("desired_capacity"),
                "mode": controller_state.get("mode"),
                "scale_out_cpu_threshold": controller_state.get("scale_out_cpu_threshold"),
                "scale_in_cpu_threshold": controller_state.get("scale_in_cpu_threshold"),
                "min_instances": controller_state.get("min_instances"),
                "max_instances": controller_state.get("max_instances"),
                "cooldown_seconds": controller_state.get("cooldown_seconds"),
                "scaling_action": scaling_action,
                "load_balancer_arn": self.config.load_balancer_arn or "",
                "auto_scaling_group_name": self.config.auto_scaling_group_name or "",
            }
        )

    def get_history(self, limit: int = 120) -> List[Dict[str, Any]]:
        return self.metrics_logger.get_recent_metrics(limit=limit)

    def get_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        local_events = self.metrics_logger.get_recent_events(limit=limit)
        aws_events = [
            {
                "timestamp": event.get("start_time"),
                "event_source": "aws",
                "event_type": "scaling_activity",
                "action": event.get("status_code"),
                "message": event.get("description"),
                "mode": "aws_managed",
                "desired_capacity": "",
                "result": event.get("status_code"),
                "details": event.get("cause"),
            }
            for event in self.aws_client.get_recent_scaling_activities(max_records=min(limit, 20))
        ]

        combined = local_events + aws_events
        combined.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
        return combined[:limit]

    def _merge_asg_metadata(
        self,
        instances: List[Dict[str, Any]],
        asg: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if not asg:
            return instances

        asg_instances = {item["instance_id"]: item for item in asg.get("instances", [])}
        merged = []
        for instance in instances:
            asg_instance = asg_instances.get(instance["instance_id"], {})
            merged.append(
                {
                    **instance,
                    "health_status": asg_instance.get("health_status", instance["health_status"]),
                    "lifecycle_state": asg_instance.get(
                        "lifecycle_state",
                        instance["lifecycle_state"],
                    ),
                    "protected_from_scale_in": asg_instance.get(
                        "protected_from_scale_in",
                        instance["protected_from_scale_in"],
                    ),
                }
            )
        return merged

    def _aggregate_series(
        self,
        series_by_key: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        buckets: Dict[str, List[float]] = defaultdict(list)
        for series in series_by_key.values():
            for point in series:
                buckets[point["timestamp"]].append(float(point["value"]))

        aggregated = [
            {
                "timestamp": timestamp,
                "value": round(sum(values) / len(values), 2),
            }
            for timestamp, values in buckets.items()
        ]
        return sorted(aggregated, key=lambda item: item["timestamp"])

    @staticmethod
    def _build_flat_series(
        primary_series: List[Dict[str, Any]],
        value: Any,
        fallback_series: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if value is None:
            return []

        anchor_series = primary_series or fallback_series
        if not anchor_series:
            return []

        return [
            {
                "timestamp": point["timestamp"],
                "value": value,
            }
            for point in anchor_series
        ]

    @staticmethod
    def _latest_value(series: List[Dict[str, Any]]) -> Any:
        if not series:
            return None
        return series[-1]["value"]

    @staticmethod
    def _latest_timestamp(*series_groups: List[Dict[str, Any]]) -> Any:
        timestamps = [
            point["timestamp"]
            for series in series_groups
            for point in (series[-1:] if series else [])
            if point.get("timestamp")
        ]
        if not timestamps:
            return None
        return max(timestamps)

    @staticmethod
    def _build_warnings(
        target_health: Dict[str, Any],
        desired_capacity: int,
        active_instance_count: int,
    ) -> List[str]:
        warnings: List[str] = []
        if not target_health:
            return warnings

        if target_health.get("error"):
            warnings.append(f"Target group health lookup failed: {target_health['error']}")
            return warnings

        counts = target_health.get("counts", {})
        if not counts:
            return warnings

        total_targets = int(counts.get("total", 0))
        healthy_targets = int(counts.get("healthy", 0))
        unhealthy_targets = int(counts.get("unhealthy", 0))

        if total_targets == 0 and desired_capacity > 0:
            warnings.append(
                "No registered targets were returned from the target group even though desired capacity is above zero."
            )

        expected_healthy_floor = min(int(desired_capacity or 0), int(active_instance_count or 0))
        if expected_healthy_floor > 0 and healthy_targets < expected_healthy_floor:
            warnings.append(
                f"Healthy targets are below expected capacity ({healthy_targets} healthy vs {expected_healthy_floor} expected)."
            )

        if unhealthy_targets > 0:
            reason_snippets = []
            for target in target_health.get("targets", []):
                if str(target.get("state")).lower() != "unhealthy":
                    continue
                reason = target.get("reason") or target.get("description")
                if reason and reason not in reason_snippets:
                    reason_snippets.append(str(reason))
                if len(reason_snippets) == 2:
                    break

            if reason_snippets:
                warnings.append(
                    "Unhealthy ALB targets detected: " + "; ".join(reason_snippets)
                )
            else:
                warnings.append("Unhealthy ALB targets detected in the attached target group.")

        return warnings
