#!/usr/bin/env python3

import argparse
import sys
from typing import Any, Dict, List, Tuple

from botocore.exceptions import BotoCoreError, ClientError

from aws_client import AWSClient
from config import CONFIG


def _format_value(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "N/A"
    return str(value)


def _print_section(title: str) -> None:
    print()
    print(title)
    print("=" * len(title))


def _load_asg(client: AWSClient, asg_name: str | None) -> Dict[str, Any] | None:
    return client.get_asg_details(asg_name=asg_name)


def _describe_load_balancer(client: AWSClient, load_balancer_arn: str) -> Dict[str, Any]:
    response = client.elbv2.describe_load_balancers(LoadBalancerArns=[load_balancer_arn])
    load_balancers = response.get("LoadBalancers", [])
    if not load_balancers:
        raise RuntimeError(f"Load balancer not found for ARN {load_balancer_arn}")
    return load_balancers[0]


def _describe_security_groups(client: AWSClient, group_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not group_ids:
        return {}
    response = client.ec2.describe_security_groups(GroupIds=group_ids)
    return {group["GroupId"]: group for group in response.get("SecurityGroups", [])}


def _allows_port_from_group(
    group: Dict[str, Any],
    source_group_ids: List[str],
    port: int,
) -> bool:
    for permission in group.get("IpPermissions", []):
        ip_protocol = permission.get("IpProtocol")
        if ip_protocol not in ("tcp", "-1"):
            continue

        from_port = permission.get("FromPort")
        to_port = permission.get("ToPort")
        if from_port is not None and to_port is not None and not (from_port <= port <= to_port):
            continue

        for user_group in permission.get("UserIdGroupPairs", []):
            if user_group.get("GroupId") in source_group_ids:
                return True

    return False


def _load_instance_security_groups(client: AWSClient, instance_ids: List[str]) -> Dict[str, List[str]]:
    if not instance_ids:
        return {}

    response = client.ec2.describe_instances(InstanceIds=instance_ids)
    mapping: Dict[str, List[str]] = {}
    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            mapping[instance["InstanceId"]] = [
                group["GroupId"] for group in instance.get("SecurityGroups", [])
            ]
    return mapping


def _evaluate_findings(
    config_port: int,
    load_balancer: Dict[str, Any],
    target_health: Dict[str, Any],
    instance_security_group_map: Dict[str, List[str]],
    security_groups: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], List[str]]:
    issues: List[str] = []
    notes: List[str] = []

    target_protocol = str(target_health.get("protocol") or "").upper()
    target_port = target_health.get("port")
    health_path = target_health.get("health_check_path")
    health_port = str(target_health.get("health_check_port") or "")
    counts = target_health.get("counts", {})
    healthy_count = int(counts.get("healthy", 0))
    total_count = int(counts.get("total", 0))

    if target_protocol and target_protocol != "HTTP":
        issues.append(f"Target group protocol is {target_protocol}; this app expects HTTP to the instance.")
    if target_port not in (None, config_port):
        issues.append(
            f"Target group forwards to port {target_port}, but the app is configured for port {config_port}."
        )
    if health_path and health_path != "/healthz":
        issues.append(f"Health check path is {health_path}; expected /healthz.")
    if health_port not in ("traffic-port", str(config_port)):
        issues.append(
            f"Health check port is {health_port}; expected traffic-port or {config_port}."
        )
    if total_count == 0:
        issues.append("Target group currently has no registered targets.")
    if total_count > 0 and healthy_count == 0:
        issues.append("Target group has registered targets but zero healthy targets.")

    alb_security_group_ids = load_balancer.get("SecurityGroups", [])
    if not alb_security_group_ids:
        notes.append("ALB security groups were not returned by the API.")

    sg_path_ok = False
    for instance_id, group_ids in instance_security_group_map.items():
        for group_id in group_ids:
            group = security_groups.get(group_id)
            if group and _allows_port_from_group(group, alb_security_group_ids, config_port):
                sg_path_ok = True
                break
        if sg_path_ok:
            break

    if instance_security_group_map and not sg_path_ok and alb_security_group_ids:
        issues.append(
            f"No instance security group rule allows TCP {config_port} from the ALB security group."
        )

    return issues, notes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose the ALB -> target group -> EC2 path for the Cloud & DevOps dashboard demo."
    )
    parser.add_argument("--asg", dest="asg_name", default=CONFIG.auto_scaling_group_name)
    parser.add_argument("--target-group-arn", dest="target_group_arn", default=CONFIG.target_group_arn)
    parser.add_argument("--load-balancer-arn", dest="load_balancer_arn", default=CONFIG.load_balancer_arn)
    parser.add_argument("--app-port", dest="app_port", type=int, default=CONFIG.app_port)
    args = parser.parse_args()

    client = AWSClient(CONFIG)

    try:
        asg = _load_asg(client, args.asg_name)
        target_group_arn = args.target_group_arn
        if not target_group_arn and asg:
            target_group_arns = asg.get("target_group_arns", [])
            target_group_arn = target_group_arns[0] if target_group_arns else None

        if not target_group_arn:
            raise RuntimeError("No target group ARN is configured or attached to the Auto Scaling Group.")

        target_health = client.get_target_group_health(target_group_arn=target_group_arn)
        if target_health.get("error"):
            raise RuntimeError(f"Target health lookup failed: {target_health['error']}")

        load_balancer_arn = args.load_balancer_arn
        if not load_balancer_arn:
            load_balancer_arns = target_health.get("load_balancer_arns", [])
            load_balancer_arn = load_balancer_arns[0] if load_balancer_arns else None

        if not load_balancer_arn:
            raise RuntimeError("No load balancer ARN is configured or attached to the target group.")

        load_balancer = _describe_load_balancer(client, load_balancer_arn)
        instance_ids = [item["instance_id"] for item in (asg or {}).get("instances", [])]
        instance_security_group_map = _load_instance_security_groups(client, instance_ids)
        all_group_ids = set(load_balancer.get("SecurityGroups", []))
        for group_ids in instance_security_group_map.values():
            all_group_ids.update(group_ids)
        security_groups = _describe_security_groups(client, sorted(all_group_ids))
        issues, notes = _evaluate_findings(
            config_port=args.app_port,
            load_balancer=load_balancer,
            target_health=target_health,
            instance_security_group_map=instance_security_group_map,
            security_groups=security_groups,
        )
    except (RuntimeError, ClientError, BotoCoreError) as exc:
        print(f"Diagnostic failed: {exc}", file=sys.stderr)
        return 1

    _print_section("Config")
    print(f"Region: {_format_value(CONFIG.aws_region)}")
    print(f"ASG: {_format_value(args.asg_name)}")
    print(f"Target Group ARN: {_format_value(target_group_arn)}")
    print(f"Load Balancer ARN: {_format_value(load_balancer_arn)}")
    print(f"App Port: {_format_value(args.app_port)}")

    _print_section("Auto Scaling Group")
    if asg:
        print(f"Desired / Min / Max: {asg.get('desired_capacity')} / {asg.get('min_size')} / {asg.get('max_size')}")
        print(f"Health Check Type: {_format_value(asg.get('health_check_type'))}")
        print(f"Cooldown: {_format_value(asg.get('default_cooldown'))}")
        print(f"Attached Target Groups: {_format_value(asg.get('target_group_arns'))}")
        print(f"Instances: {_format_value([instance.get('instance_id') for instance in asg.get('instances', [])])}")
    else:
        print("ASG details were not found.")

    _print_section("Load Balancer")
    print(f"Name: {_format_value(load_balancer.get('LoadBalancerName'))}")
    print(f"DNS Name: {_format_value(load_balancer.get('DNSName'))}")
    print(f"Scheme: {_format_value(load_balancer.get('Scheme'))}")
    print(f"State: {_format_value((load_balancer.get('State') or {}).get('Code'))}")
    print(f"Security Groups: {_format_value(load_balancer.get('SecurityGroups'))}")

    _print_section("Target Group")
    print(f"Name: {_format_value(target_health.get('target_group_name'))}")
    print(f"Protocol / Port: {_format_value(target_health.get('protocol'))} / {_format_value(target_health.get('port'))}")
    print(f"Target Type: {_format_value(target_health.get('target_type'))}")
    print(f"Health Check: {_format_value(target_health.get('health_check_protocol'))} {_format_value(target_health.get('health_check_port'))} {_format_value(target_health.get('health_check_path'))}")
    print(
        "Health Timeout / Interval: "
        f"{_format_value(target_health.get('health_check_timeout_seconds'))} / "
        f"{_format_value(target_health.get('health_check_interval_seconds'))}"
    )
    print(f"Success Codes: {_format_value(target_health.get('matcher'))}")

    _print_section("Target Health")
    counts = target_health.get("counts", {})
    print(
        "Healthy / Unhealthy / Initial / Total: "
        f"{counts.get('healthy', 0)} / {counts.get('unhealthy', 0)} / {counts.get('initial', 0)} / {counts.get('total', 0)}"
    )
    for target in target_health.get("targets", []):
        state = _format_value(target.get("state"))
        reason = _format_value(target.get("reason"))
        description = _format_value(target.get("description"))
        print(
            f"- {target.get('id')}:{target.get('port')} state={state} reason={reason} description={description}"
        )

    _print_section("Security Group Path")
    if instance_security_group_map:
        for instance_id, group_ids in instance_security_group_map.items():
            names = [
                security_groups.get(group_id, {}).get("GroupName", group_id)
                for group_id in group_ids
            ]
            print(f"- {instance_id}: {_format_value(names)}")
    else:
        print("No instance security groups were discovered from the ASG instances.")

    _print_section("Verdict")
    if issues:
        print("Issues found:")
        for issue in issues:
            print(f"- {issue}")
    else:
        print("No obvious ALB -> target group -> instance misconfiguration was detected.")

    if notes:
        print("Notes:")
        for note in notes:
            print(f"- {note}")

    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
