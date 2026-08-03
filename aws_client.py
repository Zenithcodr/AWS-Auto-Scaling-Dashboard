import logging
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from datetime import datetime, timedelta, timezone

from config import AppConfig


LOGGER = logging.getLogger(__name__)


def _tags_to_dict(tags: Optional[List[Dict[str, str]]]) -> Dict[str, str]:
    return {tag["Key"]: tag["Value"] for tag in tags or []}


def _dimension_from_arn(arn: Optional[str], marker: str) -> Optional[str]:
    if not arn or f"{marker}/" not in arn:
        return None
    return arn.split(f"{marker}/", 1)[1]


class AWSClient:
    def __init__(self, config: AppConfig):
        self.config = config
        self.session = boto3.Session(**config.boto3_session_kwargs())
        self.ec2 = self.session.client("ec2")
        self.cloudwatch = self.session.client("cloudwatch")
        self.autoscaling = self.session.client("autoscaling")
        self.elbv2 = self.session.client("elbv2")
        self.s3 = self.session.client("s3")

    def get_ec2_instances(self) -> List[Dict[str, Any]]:
        filters: List[Dict[str, Any]] = []
        if self.config.auto_scaling_group_name:
            filters.append(
                {
                    "Name": "tag:aws:autoscaling:groupName",
                    "Values": [self.config.auto_scaling_group_name],
                }
            )
        if self.config.ec2_tag_key and self.config.ec2_tag_value:
            filters.append(
                {
                    "Name": f"tag:{self.config.ec2_tag_key}",
                    "Values": [self.config.ec2_tag_value],
                }
            )

        describe_kwargs: Dict[str, Any] = {}
        if filters:
            describe_kwargs["Filters"] = filters

        response = self.ec2.describe_instances(**describe_kwargs)
        instances: List[Dict[str, Any]] = []

        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                launch_time = instance.get("LaunchTime")
                instances.append(
                    {
                        "instance_id": instance["InstanceId"],
                        "state": instance["State"]["Name"],
                        "instance_type": instance.get("InstanceType"),
                        "private_ip": instance.get("PrivateIpAddress"),
                        "public_ip": instance.get("PublicIpAddress"),
                        "launch_time": launch_time.astimezone(timezone.utc).isoformat()
                        if launch_time
                        else None,
                        "availability_zone": instance.get("Placement", {}).get("AvailabilityZone"),
                        "tags": _tags_to_dict(instance.get("Tags")),
                        "health_status": "unknown",
                        "lifecycle_state": "standalone",
                        "protected_from_scale_in": False,
                    }
                )

        return sorted(
            instances,
            key=lambda item: item.get("launch_time") or "",
            reverse=True,
        )

    def get_asg_details(self, asg_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        target_name = asg_name or self.config.auto_scaling_group_name
        if not target_name:
            return None

        response = self.autoscaling.describe_auto_scaling_groups(
            AutoScalingGroupNames=[target_name]
        )
        groups = response.get("AutoScalingGroups", [])
        if not groups:
            return None

        group = groups[0]
        return {
            "name": group["AutoScalingGroupName"],
            "min_size": group["MinSize"],
            "max_size": group["MaxSize"],
            "desired_capacity": group["DesiredCapacity"],
            "default_cooldown": group.get("DefaultCooldown", 0),
            "health_check_type": group.get("HealthCheckType"),
            "health_check_grace_period": group.get("HealthCheckGracePeriod"),
            "availability_zones": group.get("AvailabilityZones", []),
            "instances": [
                {
                    "instance_id": instance["InstanceId"],
                    "health_status": instance.get("HealthStatus"),
                    "lifecycle_state": instance.get("LifecycleState"),
                    "availability_zone": instance.get("AvailabilityZone"),
                    "protected_from_scale_in": instance.get("ProtectedFromScaleIn", False),
                }
                for instance in group.get("Instances", [])
            ],
            "target_group_arns": group.get("TargetGroupARNs", []),
            "suspended_processes": [
                process.get("ProcessName") for process in group.get("SuspendedProcesses", [])
            ],
        }

    def get_recent_scaling_activities(
        self,
        asg_name: Optional[str] = None,
        max_records: int = 20,
    ) -> List[Dict[str, Any]]:
        target_name = asg_name or self.config.auto_scaling_group_name
        if not target_name:
            return []

        response = self.autoscaling.describe_scaling_activities(
            AutoScalingGroupName=target_name,
            MaxRecords=max_records,
        )

        activities = []
        for item in response.get("Activities", []):
            activities.append(
                {
                    "activity_id": item.get("ActivityId"),
                    "description": item.get("Description"),
                    "cause": item.get("Cause"),
                    "start_time": item.get("StartTime").astimezone(timezone.utc).isoformat()
                    if item.get("StartTime")
                    else None,
                    "end_time": item.get("EndTime").astimezone(timezone.utc).isoformat()
                    if item.get("EndTime")
                    else None,
                    "status_code": item.get("StatusCode"),
                    "progress": item.get("Progress"),
                    "details": item.get("Details"),
                }
            )
        return activities

    def get_metric_series(
        self,
        namespace: str,
        metric_name: str,
        dimensions: List[Dict[str, str]],
        stat: str = "Average",
        period: Optional[int] = None,
        minutes: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        effective_period = period or self.config.metric_period_seconds
        effective_window = minutes or self.config.metric_window_minutes
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=effective_window)

        try:
            response = self.cloudwatch.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start_time,
                EndTime=end_time,
                Period=effective_period,
                Statistics=[stat],
            )
        except (ClientError, BotoCoreError) as exc:
            LOGGER.warning(
                "Unable to fetch CloudWatch metric %s/%s: %s",
                namespace,
                metric_name,
                exc,
            )
            return []

        datapoints = response.get("Datapoints", [])
        sorted_points = sorted(datapoints, key=lambda point: point["Timestamp"])
        return [
            {
                "timestamp": point["Timestamp"].astimezone(timezone.utc).isoformat(),
                "value": round(float(point.get(stat, 0.0)), 2),
            }
            for point in sorted_points
        ]

    def get_instance_cpu_metrics(self, instance_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        metrics: Dict[str, List[Dict[str, Any]]] = {}
        for instance_id in instance_ids:
            metrics[instance_id] = self.get_metric_series(
                namespace="AWS/EC2",
                metric_name="CPUUtilization",
                dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                stat="Average",
            )
        return metrics

    def get_alb_request_series(self, load_balancer_arn: Optional[str] = None) -> List[Dict[str, Any]]:
        dimension_value = _dimension_from_arn(
            load_balancer_arn or self.config.load_balancer_arn,
            "loadbalancer",
        )
        if not dimension_value:
            return []

        return self.get_metric_series(
            namespace="AWS/ApplicationELB",
            metric_name="RequestCount",
            dimensions=[{"Name": "LoadBalancer", "Value": dimension_value}],
            stat="Sum",
        )

    def get_alb_target_health_series(
        self,
        load_balancer_arn: Optional[str] = None,
        target_group_arn: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        load_balancer_dimension = _dimension_from_arn(
            load_balancer_arn or self.config.load_balancer_arn,
            "loadbalancer",
        )
        target_group_dimension = _dimension_from_arn(
            target_group_arn or self.config.target_group_arn,
            "targetgroup",
        )

        if not load_balancer_dimension or not target_group_dimension:
            return []

        return self.get_metric_series(
            namespace="AWS/ApplicationELB",
            metric_name="HealthyHostCount",
            dimensions=[
                {"Name": "LoadBalancer", "Value": load_balancer_dimension},
                {"Name": "TargetGroup", "Value": target_group_dimension},
            ],
            stat="Average",
        )

    def get_target_group_health(
        self,
        target_group_arn: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_target_group_arn = target_group_arn or self.config.target_group_arn
        if not resolved_target_group_arn:
            return {
                "configured": False,
                "target_group_arn": None,
                "counts": {},
                "targets": [],
            }

        try:
            response = self.elbv2.describe_target_groups(
                TargetGroupArns=[resolved_target_group_arn]
            )
        except (ClientError, BotoCoreError) as exc:
            LOGGER.warning(
                "Unable to describe target group %s: %s",
                resolved_target_group_arn,
                exc,
            )
            return {
                "configured": True,
                "target_group_arn": resolved_target_group_arn,
                "counts": {},
                "targets": [],
                "error": str(exc),
            }

        groups = response.get("TargetGroups", [])
        if not groups:
            return {
                "configured": True,
                "target_group_arn": resolved_target_group_arn,
                "counts": {},
                "targets": [],
                "error": "Target group was not found.",
            }

        group = groups[0]
        try:
            health_response = self.elbv2.describe_target_health(
                TargetGroupArn=resolved_target_group_arn
            )
        except (ClientError, BotoCoreError) as exc:
            LOGGER.warning(
                "Unable to fetch target health for %s: %s",
                resolved_target_group_arn,
                exc,
            )
            return {
                "configured": True,
                "target_group_arn": resolved_target_group_arn,
                "target_group_name": group.get("TargetGroupName"),
                "counts": {},
                "targets": [],
                "error": str(exc),
            }

        counts: Dict[str, int] = {
            "healthy": 0,
            "unhealthy": 0,
            "initial": 0,
            "draining": 0,
            "unused": 0,
            "unavailable": 0,
            "unknown": 0,
        }
        targets: List[Dict[str, Any]] = []

        for item in health_response.get("TargetHealthDescriptions", []):
            target = item.get("Target", {})
            target_health = item.get("TargetHealth", {})
            state = str(target_health.get("State") or "unknown").lower()
            counts[state] = counts.get(state, 0) + 1
            targets.append(
                {
                    "id": target.get("Id"),
                    "port": target.get("Port"),
                    "availability_zone": target.get("AvailabilityZone"),
                    "state": state,
                    "reason": target_health.get("Reason"),
                    "description": target_health.get("Description"),
                }
            )

        counts["total"] = len(targets)

        return {
            "configured": True,
            "target_group_arn": resolved_target_group_arn,
            "target_group_name": group.get("TargetGroupName"),
            "protocol": group.get("Protocol"),
            "port": group.get("Port"),
            "target_type": group.get("TargetType"),
            "health_check_protocol": group.get("HealthCheckProtocol"),
            "health_check_port": group.get("HealthCheckPort"),
            "health_check_path": group.get("HealthCheckPath"),
            "health_check_interval_seconds": group.get("HealthCheckIntervalSeconds"),
            "health_check_timeout_seconds": group.get("HealthCheckTimeoutSeconds"),
            "matcher": group.get("Matcher", {}).get("HttpCode"),
            "load_balancer_arns": group.get("LoadBalancerArns", []),
            "counts": counts,
            "targets": targets,
        }

    def set_desired_capacity(
        self,
        desired_capacity: int,
        asg_name: Optional[str] = None,
        honor_cooldown: bool = False,
    ) -> Dict[str, Any]:
        target_name = asg_name or self.config.auto_scaling_group_name
        if not target_name:
            raise ValueError("AUTO_SCALING_GROUP_NAME must be configured for scaling actions.")

        self.autoscaling.set_desired_capacity(
            AutoScalingGroupName=target_name,
            DesiredCapacity=desired_capacity,
            HonorCooldown=honor_cooldown,
        )

        return {
            "status": "submitted",
            "asg_name": target_name,
            "desired_capacity": desired_capacity,
            "honor_cooldown": honor_cooldown,
        }

    def update_auto_scaling_group(
        self,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
        default_cooldown: Optional[int] = None,
        desired_capacity: Optional[int] = None,
        asg_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        target_name = asg_name or self.config.auto_scaling_group_name
        if not target_name:
            raise ValueError("AUTO_SCALING_GROUP_NAME must be configured for ASG updates.")

        update_kwargs: Dict[str, Any] = {"AutoScalingGroupName": target_name}
        if min_size is not None:
            update_kwargs["MinSize"] = min_size
        if max_size is not None:
            update_kwargs["MaxSize"] = max_size
        if default_cooldown is not None:
            update_kwargs["DefaultCooldown"] = default_cooldown
        if desired_capacity is not None:
            update_kwargs["DesiredCapacity"] = desired_capacity

        self.autoscaling.update_auto_scaling_group(**update_kwargs)

        return {
            "status": "updated",
            "asg_name": target_name,
            "min_size": min_size,
            "max_size": max_size,
            "default_cooldown": default_cooldown,
            "desired_capacity": desired_capacity,
        }

    def upload_file_to_s3(
        self,
        local_path: str,
        bucket_name: Optional[str] = None,
        key: Optional[str] = None,
    ) -> bool:
        bucket = bucket_name or self.config.s3_log_bucket
        if not bucket:
            return False

        target_key = key or local_path.split("/")[-1]
        self.s3.upload_file(local_path, bucket, target_key)
        return True
