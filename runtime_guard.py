import os
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Mapping, Optional


AWS_RUNTIME_ENV_VARS = (
    "AWS_EXECUTION_ENV",
    "ECS_CONTAINER_METADATA_URI",
    "ECS_CONTAINER_METADATA_URI_V4",
    "EKS_CLUSTER_NAME",
)


def _normalise_policy(policy: Optional[str]) -> str:
    return (policy or "local_only").strip().lower()


def ec2_metadata_available(timeout_seconds: float = 0.25) -> bool:
    request = urllib.request.Request(
        "http://169.254.169.254/latest/meta-data/instance-id",
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return 200 <= response.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code in {401, 403, 404}
    except (OSError, TimeoutError, urllib.error.URLError):
        return False


def detect_aws_runtime_indicators(
    env: Optional[Mapping[str, str]] = None,
    metadata_probe: Optional[Callable[[], bool]] = None,
) -> List[str]:
    runtime_env = env or os.environ
    indicators = [
        name for name in AWS_RUNTIME_ENV_VARS if runtime_env.get(name, "").strip()
    ]

    probe = metadata_probe or ec2_metadata_available
    if probe():
        indicators.append("ec2-instance-metadata")

    return indicators


def enforce_local_dashboard_runtime(
    policy: Optional[str],
    allow_dashboard_on_aws: bool,
    env: Optional[Mapping[str, str]] = None,
    metadata_probe: Optional[Callable[[], bool]] = None,
) -> Dict[str, object]:
    normalised_policy = _normalise_policy(policy)
    indicators = detect_aws_runtime_indicators(env=env, metadata_probe=metadata_probe)

    status: Dict[str, object] = {
        "policy": normalised_policy,
        "deployment_model": "local-dashboard-remote-aws-resources",
        "aws_runtime_indicators": indicators,
    }

    if normalised_policy not in {"local_only", "mac_local_only"}:
        status["status"] = "unrestricted"
        return status

    if indicators and not allow_dashboard_on_aws:
        joined_indicators = ", ".join(indicators)
        raise RuntimeError(
            "Dashboard runtime policy is local_only. Run this monitoring dashboard "
            "on the operator Mac with Docker Compose. AWS should host only the "
            "Terraform-created resources and the Ansible-configured workload target. "
            f"Detected AWS runtime indicators: {joined_indicators}."
        )

    status["status"] = "local" if not indicators else "aws-override-enabled"
    return status
