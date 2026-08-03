import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from aws_client import AWSClient
from config import AppConfig, SUPPORTED_SCALING_MODES
from metrics_logger import MetricsLogger


LOGGER = logging.getLogger(__name__)


def _coerce_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if value is None:
        return False

    normalised = str(value).strip().lower()
    if normalised in {"1", "true", "yes", "on"}:
        return True
    if normalised in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{field_name} must be a boolean value.")


class ScalingController:
    def __init__(self, config: AppConfig, aws_client: AWSClient, metrics_logger: MetricsLogger):
        self.config = config
        self.aws_client = aws_client
        self.metrics_logger = metrics_logger
        self.state = self._load_state()

    def get_state(self) -> Dict[str, Any]:
        return deepcopy(self.state)

    def apply_control_action(
        self,
        payload: Dict[str, Any],
        snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.config.control_enabled:
            raise PermissionError("Control actions are disabled by configuration.")

        action = (payload.get("action") or "update_settings").strip()
        if action == "update_settings":
            return self.update_settings(payload)
        if action == "refresh":
            return {"status": "ok", "action": "refresh", "reason": "Manual refresh requested."}
        if action == "evaluate_now":
            if not snapshot:
                raise ValueError("A current infrastructure snapshot is required for evaluation.")
            return self.evaluate(snapshot, source="manual")
        if action in {"force_scale_out", "force_scale_in"}:
            if not snapshot:
                raise ValueError("A current infrastructure snapshot is required for manual scaling.")
            return self._force_scale(action, snapshot)
        raise ValueError(f"Unsupported control action: {action}")

    def update_settings(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        updated_state = deepcopy(self.state)

        if "mode" in payload:
            mode = str(payload["mode"]).strip().lower()
            if mode not in SUPPORTED_SCALING_MODES:
                raise ValueError(f"mode must be one of {', '.join(SUPPORTED_SCALING_MODES)}")
            updated_state["mode"] = mode

        for field_name in ("scale_out_cpu_threshold", "scale_in_cpu_threshold"):
            if field_name in payload:
                updated_state[field_name] = float(payload[field_name])

        for field_name in ("min_instances", "max_instances", "cooldown_seconds"):
            if field_name in payload:
                updated_state[field_name] = int(payload[field_name])

        if "active_control" in payload:
            updated_state["active_control"] = _coerce_bool(
                payload["active_control"],
                "active_control",
            )

        self._validate_state(updated_state)
        aws_sync = self._sync_state_to_aws(updated_state)
        if aws_sync["status"] == "updated":
            updated_state["last_reason"] = (
                "Controller settings updated and synchronized to the AWS Auto Scaling Group."
            )
        else:
            updated_state["last_reason"] = f"Controller settings updated locally. {aws_sync['reason']}"
        if aws_sync.get("desired_capacity") is not None:
            updated_state["latest_desired_capacity"] = aws_sync.get("desired_capacity")
        self.state = updated_state
        self._save_state()

        self.metrics_logger.log_event(
            {
                "event_source": "control_api",
                "event_type": "configuration_change",
                "action": "update_settings",
                "message": "Scaling controller configuration updated.",
                "mode": self.state["mode"],
                "desired_capacity": self.state.get("latest_desired_capacity", ""),
                "result": "success",
                "details": json.dumps({"state": self.state, "aws_sync": aws_sync}),
            }
        )
        return {
            "status": "updated",
            "action": "update_settings",
            "state": self.get_state(),
            "message": updated_state["last_reason"],
            "aws_sync": aws_sync,
        }

    def evaluate(self, snapshot: Dict[str, Any], source: str = "automatic") -> Dict[str, Any]:
        state = self._reconcile_state_with_asg(self.get_state(), snapshot.get("asg"))
        if state["mode"] != "custom":
            state["last_reason"] = "Controller is in aws_managed mode; only monitoring decisions."
            self.state = state
            self._save_state()
            return self._build_noop_response("aws_managed mode is active.")

        if not state["active_control"]:
            state["last_reason"] = "Active control is disabled; monitoring only."
            self.state = state
            self._save_state()
            return self._build_noop_response("Active control is disabled.")

        if not self.config.auto_scaling_group_name:
            state["last_reason"] = "AUTO_SCALING_GROUP_NAME is missing."
            self.state = state
            self._save_state()
            return self._build_noop_response("AUTO_SCALING_GROUP_NAME is not configured.")

        summary = snapshot.get("summary", {})
        average_cpu = summary.get("average_cpu")
        current_instance_count = summary.get("instance_count")
        current_request_count = summary.get("request_count")
        current_desired = summary.get("desired_capacity")
        latest_cpu_timestamp = self._latest_series_timestamp(snapshot, "cpu")
        if current_desired is None:
            current_desired = current_instance_count or state["min_instances"]

        if average_cpu is None:
            state["last_reason"] = "CloudWatch did not return CPU data for the current interval."
            self.state = state
            self._save_state()
            return self._build_noop_response("Average CPU metric is unavailable.")

        if source == "automatic":
            if latest_cpu_timestamp is None:
                state["last_reason"] = "CPU sample timestamp is unavailable for the current interval."
                self.state = state
                self._save_state()
                return self._build_noop_response(state["last_reason"])

            if latest_cpu_timestamp == state.get("last_processed_cpu_timestamp"):
                state["last_reason"] = (
                    f"Latest CPU sample {latest_cpu_timestamp} was already evaluated."
                )
                self.state = state
                self._save_state()
                return self._build_noop_response(state["last_reason"])

        if (
            current_instance_count is not None
            and current_desired is not None
            and int(current_instance_count) != int(current_desired)
        ):
            reason = (
                f"Capacity is still converging: actual active instances {int(current_instance_count)} "
                f"do not match desired capacity {int(current_desired)} yet."
            )
            state["last_reason"] = reason
            if source == "automatic":
                state["last_processed_cpu_timestamp"] = latest_cpu_timestamp
            self.state = state
            self._save_state()
            return self._build_noop_response(reason)

        cooldown_remaining = self._cooldown_remaining(state)
        if cooldown_remaining > 0 and source == "automatic":
            state["last_reason"] = f"Cooldown active for {cooldown_remaining} more seconds."
            state["last_processed_cpu_timestamp"] = latest_cpu_timestamp
            self.state = state
            self._save_state()
            return self._build_noop_response(state["last_reason"])

        recent_cpu_values = self._recent_series_values(
            snapshot,
            "cpu",
            limit=max(
                self.config.scaler_scale_out_confirmation_samples,
                self.config.scaler_scale_in_confirmation_samples,
            ),
        )
        recent_request_values = self._recent_series_values(
            snapshot,
            "request_count",
            limit=max(3, self.config.scaler_scale_in_confirmation_samples),
        )
        high_cpu_confirmed = self._series_matches_threshold(
            recent_cpu_values,
            state["scale_out_cpu_threshold"],
            direction="above",
            required_samples=self.config.scaler_scale_out_confirmation_samples,
        )
        low_cpu_confirmed = self._series_matches_threshold(
            recent_cpu_values,
            state["scale_in_cpu_threshold"],
            direction="below",
            required_samples=self.config.scaler_scale_in_confirmation_samples,
        )
        scale_in_request_signal = self._has_request_signal(
            current_request_count,
            recent_request_values,
            minimum_request_threshold=self.config.scaler_request_signal_threshold,
        )
        scale_out_request_signal = self._has_request_signal(
            current_request_count,
            recent_request_values,
            minimum_request_threshold=self.config.scaler_scale_out_request_signal_threshold,
        )

        if average_cpu >= state["scale_out_cpu_threshold"] and current_desired < state["max_instances"]:
            effective_scale_out_confirmation_samples = self._effective_scale_out_confirmation_samples(
                average_cpu=float(average_cpu),
                scale_out_threshold=float(state["scale_out_cpu_threshold"]),
                request_signal=scale_out_request_signal,
            )
            high_cpu_confirmed = self._series_matches_threshold(
                recent_cpu_values,
                state["scale_out_cpu_threshold"],
                direction="above",
                required_samples=effective_scale_out_confirmation_samples,
            )
            if not high_cpu_confirmed:
                reason = (
                    f"Average CPU {average_cpu}% crossed the scale-out threshold, but "
                    f"{self._sample_phrase(effective_scale_out_confirmation_samples)} "
                    "have not confirmed the spike yet."
                )
                state["last_reason"] = reason
                if source == "automatic":
                    state["last_processed_cpu_timestamp"] = latest_cpu_timestamp
                self.state = state
                self._save_state()
                return self._build_noop_response(reason)

            scale_out_step = self._determine_scale_out_step(
                average_cpu=float(average_cpu),
                current_desired=int(current_desired),
                max_instances=int(state["max_instances"]),
                scale_out_threshold=float(state["scale_out_cpu_threshold"]),
                request_signal=scale_out_request_signal,
            )
            reason = (
                f"Average CPU {average_cpu}% is above the scale-out threshold "
                f"{state['scale_out_cpu_threshold']}%."
            )
            if scale_out_step > 1:
                reason += f" Demo-fast overload scale-out will add {scale_out_step} instances."
            return self._submit_scaling_action(
                action="scale_out",
                desired_capacity=int(current_desired) + scale_out_step,
                reason=reason,
                source=source,
                signal_timestamp=latest_cpu_timestamp,
                state=state,
            )

        if average_cpu <= state["scale_in_cpu_threshold"] and current_desired > state["min_instances"]:
            if scale_in_request_signal:
                reason = (
                    f"Average CPU {average_cpu}% is low, but recent ALB request activity is still present "
                    f"above the idle threshold of {self.config.scaler_request_signal_threshold} requests."
                )
                state["last_reason"] = reason
                if source == "automatic":
                    state["last_processed_cpu_timestamp"] = latest_cpu_timestamp
                self.state = state
                self._save_state()
                return self._build_noop_response(reason)

            if not low_cpu_confirmed:
                reason = (
                    f"Average CPU {average_cpu}% is below the scale-in threshold, but "
                    f"{self._sample_phrase(self.config.scaler_scale_in_confirmation_samples)} "
                    "have not confirmed the drop yet."
                )
                state["last_reason"] = reason
                if source == "automatic":
                    state["last_processed_cpu_timestamp"] = latest_cpu_timestamp
                self.state = state
                self._save_state()
                return self._build_noop_response(reason)

            scale_in_step = self._determine_scale_in_step(
                average_cpu=float(average_cpu),
                current_desired=int(current_desired),
                min_instances=int(state["min_instances"]),
                scale_in_threshold=float(state["scale_in_cpu_threshold"]),
                current_request_count=current_request_count,
                recent_request_values=recent_request_values,
            )
            reason = (
                f"Average CPU {average_cpu}% is below the scale-in threshold "
                f"{state['scale_in_cpu_threshold']}%."
            )
            if scale_in_step > 1:
                reason += f" Demo-fast idle scale-in will reduce capacity by {scale_in_step} instances."
            return self._submit_scaling_action(
                action="scale_in",
                desired_capacity=int(current_desired) - scale_in_step,
                reason=reason,
                source=source,
                signal_timestamp=latest_cpu_timestamp,
                state=state,
            )

        state["last_reason"] = "Metrics are within thresholds or the controller is at its bounds."
        if source == "automatic":
            state["last_processed_cpu_timestamp"] = latest_cpu_timestamp
        self.state = state
        self._save_state()
        return self._build_noop_response(state["last_reason"])

    def _force_scale(self, action: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        if not self.config.control_allow_force:
            raise ValueError("Manual force actions are disabled by configuration.")
        if not self.config.auto_scaling_group_name:
            raise ValueError("AUTO_SCALING_GROUP_NAME is required for manual scaling.")

        state = self._reconcile_state_with_asg(self.get_state(), snapshot.get("asg"))
        current_desired = (
            snapshot.get("summary", {}).get("desired_capacity")
            or snapshot.get("summary", {}).get("instance_count")
            or state["min_instances"]
        )

        if action == "force_scale_out":
            desired_capacity = min(int(current_desired) + 1, state["max_instances"])
            reason = "Manual force scale-out requested from the control panel."
            scale_action = "scale_out"
        else:
            desired_capacity = max(int(current_desired) - 1, state["min_instances"])
            reason = "Manual force scale-in requested from the control panel."
            scale_action = "scale_in"

        if desired_capacity == int(current_desired):
            return self._build_noop_response("Desired capacity is already at the configured bound.")

        return self._submit_scaling_action(
            action=scale_action,
            desired_capacity=desired_capacity,
            reason=reason,
            source="manual_force",
            state=state,
        )

    def _submit_scaling_action(
        self,
        action: str,
        desired_capacity: int,
        reason: str,
        source: str,
        signal_timestamp: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = deepcopy(state or self.get_state())
        desired_capacity = max(state["min_instances"], min(state["max_instances"], desired_capacity))

        try:
            response = self.aws_client.set_desired_capacity(
                desired_capacity=desired_capacity,
                honor_cooldown=False,
            )
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.exception("Scaling action failed")
            error_reason = f"{reason} AWS rejected the scaling request: {exc}"
            state["last_reason"] = error_reason
            if signal_timestamp:
                state["last_processed_cpu_timestamp"] = signal_timestamp
            self.state = state
            self._save_state()
            self.metrics_logger.log_event(
                {
                    "event_source": "controller",
                    "event_type": "scaling_decision",
                    "action": action,
                    "message": error_reason,
                    "mode": state["mode"],
                    "desired_capacity": desired_capacity,
                    "result": "error",
                    "details": str(exc),
                }
            )
            return {
                "status": "error",
                "action": action,
                "desired_capacity": desired_capacity,
                "reason": error_reason,
                "source": source,
            }

        state["last_action"] = action
        state["last_action_at"] = datetime.now(timezone.utc).isoformat()
        state["last_reason"] = reason
        state["latest_desired_capacity"] = desired_capacity
        if signal_timestamp:
            state["last_processed_cpu_timestamp"] = signal_timestamp
        self.state = state
        self._save_state()

        self.metrics_logger.log_event(
            {
                "event_source": "controller",
                "event_type": "scaling_decision",
                "action": action,
                "message": reason,
                "mode": state["mode"],
                "desired_capacity": desired_capacity,
                "result": "submitted",
                "details": json.dumps({"source": source, "response": response}),
            }
        )
        return {
            "status": "submitted",
            "action": action,
            "desired_capacity": desired_capacity,
            "reason": reason,
            "source": source,
        }

    def _sync_state_to_aws(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if not self.config.auto_scaling_group_name:
            return {
                "status": "skipped",
                "reason": "AWS sync skipped because AUTO_SCALING_GROUP_NAME is not configured.",
            }

        current_asg = None
        current_desired = None
        try:
            current_asg = self.aws_client.get_asg_details()
            if current_asg and current_asg.get("desired_capacity") is not None:
                current_desired = int(current_asg["desired_capacity"])
        except Exception as exc:  # pylint: disable=broad-except
            LOGGER.warning("Unable to read existing ASG details before update: %s", exc)

        desired_capacity = None
        if current_desired is not None:
            desired_capacity = max(state["min_instances"], min(state["max_instances"], current_desired))

        response = self.aws_client.update_auto_scaling_group(
            min_size=state["min_instances"],
            max_size=state["max_instances"],
            default_cooldown=state["cooldown_seconds"],
            desired_capacity=desired_capacity if desired_capacity != current_desired else None,
        )
        if desired_capacity is None and current_desired is not None:
            response["desired_capacity"] = current_desired
        return response

    def _reconcile_state_with_asg(
        self,
        state: Dict[str, Any],
        asg: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not asg:
            return state

        reconciled = deepcopy(state)
        changed = False

        live_min = asg.get("min_size")
        live_max = asg.get("max_size")
        live_cooldown = asg.get("default_cooldown")
        live_desired = asg.get("desired_capacity")

        if live_min is not None and int(live_min) != int(reconciled["min_instances"]):
            reconciled["min_instances"] = int(live_min)
            changed = True

        if live_max is not None and int(live_max) != int(reconciled["max_instances"]):
            reconciled["max_instances"] = int(live_max)
            changed = True

        if live_cooldown is not None and int(live_cooldown) != int(reconciled["cooldown_seconds"]):
            reconciled["cooldown_seconds"] = int(live_cooldown)
            changed = True

        if live_desired is not None and reconciled.get("latest_desired_capacity") != int(live_desired):
            reconciled["latest_desired_capacity"] = int(live_desired)
            changed = True

        if changed:
            self._validate_state(reconciled)

        return reconciled

    def _determine_scale_in_step(
        self,
        average_cpu: float,
        current_desired: int,
        min_instances: int,
        scale_in_threshold: float,
        current_request_count: Any,
        recent_request_values: list[float],
    ) -> int:
        available_reduction = max(0, current_desired - min_instances)
        if available_reduction <= 0:
            return 0

        idle_collapse_floor = scale_in_threshold * float(self.config.scaler_idle_collapse_cpu_ratio)
        if (
            available_reduction > 1
            and average_cpu <= idle_collapse_floor
            and self._all_request_values_below_threshold(
                current_request_count=current_request_count,
                recent_request_values=recent_request_values,
                threshold=self.config.scaler_request_signal_threshold,
            )
        ):
            return available_reduction

        fast_step = max(1, int(self.config.scaler_fast_scale_in_step))
        fast_scale_in_floor = scale_in_threshold * float(self.config.scaler_fast_scale_in_cpu_ratio)
        if available_reduction >= fast_step and average_cpu <= fast_scale_in_floor:
            return min(fast_step, available_reduction)

        return 1

    def _effective_scale_out_confirmation_samples(
        self,
        average_cpu: float,
        scale_out_threshold: float,
        request_signal: bool,
    ) -> int:
        if request_signal:
            return max(1, int(self.config.scaler_scale_out_confirmation_samples))

        fast_scale_out_floor = scale_out_threshold * float(self.config.scaler_fast_scale_out_cpu_ratio)
        if average_cpu >= fast_scale_out_floor:
            return 1

        return max(2, int(self.config.scaler_scale_out_confirmation_samples))

    def _determine_scale_out_step(
        self,
        average_cpu: float,
        current_desired: int,
        max_instances: int,
        scale_out_threshold: float,
        request_signal: bool,
    ) -> int:
        available_addition = max(0, max_instances - current_desired)
        if available_addition <= 0:
            return 0

        fast_step = max(1, int(self.config.scaler_fast_scale_out_step))
        fast_scale_out_floor = scale_out_threshold * float(self.config.scaler_fast_scale_out_cpu_ratio)
        if available_addition >= fast_step and average_cpu >= scale_out_threshold:
            if request_signal or average_cpu >= fast_scale_out_floor:
                return min(fast_step, available_addition)

        return 1

    def _validate_state(self, state: Dict[str, Any]) -> None:
        if state["scale_in_cpu_threshold"] >= state["scale_out_cpu_threshold"]:
            raise ValueError("scale_in_cpu_threshold must be lower than scale_out_cpu_threshold.")
        if not 1 <= state["scale_in_cpu_threshold"] <= 100:
            raise ValueError("scale_in_cpu_threshold must be between 1 and 100.")
        if not 1 <= state["scale_out_cpu_threshold"] <= 100:
            raise ValueError("scale_out_cpu_threshold must be between 1 and 100.")
        if state["min_instances"] < self.config.scaler_hard_min_instances:
            raise ValueError(
                f"min_instances cannot be lower than {self.config.scaler_hard_min_instances}."
            )
        if state["max_instances"] > self.config.scaler_hard_max_instances:
            raise ValueError(
                f"max_instances cannot be higher than {self.config.scaler_hard_max_instances}."
            )
        if state["min_instances"] > state["max_instances"]:
            raise ValueError("min_instances cannot be greater than max_instances.")
        if state["cooldown_seconds"] < 0:
            raise ValueError("cooldown_seconds must be zero or greater.")
        if self.config.scaler_scale_out_confirmation_samples < 1:
            raise ValueError("SCALER_SCALE_OUT_CONFIRMATION_SAMPLES must be at least 1.")
        if self.config.scaler_scale_in_confirmation_samples < 1:
            raise ValueError("SCALER_SCALE_IN_CONFIRMATION_SAMPLES must be at least 1.")
        if self.config.scaler_request_signal_threshold < 0:
            raise ValueError("SCALER_REQUEST_SIGNAL_THRESHOLD must be zero or greater.")
        if self.config.scaler_scale_out_request_signal_threshold < 0:
            raise ValueError("SCALER_SCALE_OUT_REQUEST_SIGNAL_THRESHOLD must be zero or greater.")
        if self.config.scaler_fast_scale_out_step < 1:
            raise ValueError("SCALER_FAST_SCALE_OUT_STEP must be at least 1.")
        if not 0 < self.config.scaler_fast_scale_out_cpu_ratio <= 3:
            raise ValueError("SCALER_FAST_SCALE_OUT_CPU_RATIO must be greater than 0 and at most 3.")
        if self.config.scaler_fast_scale_in_step < 1:
            raise ValueError("SCALER_FAST_SCALE_IN_STEP must be at least 1.")
        if not 0 < self.config.scaler_fast_scale_in_cpu_ratio <= 1:
            raise ValueError("SCALER_FAST_SCALE_IN_CPU_RATIO must be greater than 0 and at most 1.")
        if not 0 < self.config.scaler_idle_collapse_cpu_ratio <= 1:
            raise ValueError("SCALER_IDLE_COLLAPSE_CPU_RATIO must be greater than 0 and at most 1.")

    def _cooldown_remaining(self, state: Optional[Dict[str, Any]] = None) -> int:
        effective_state = state or self.state
        last_action_at = effective_state.get("last_action_at")
        if not last_action_at or effective_state.get("last_action") not in {"scale_out", "scale_in"}:
            return 0

        last_timestamp = datetime.fromisoformat(last_action_at)
        elapsed = (datetime.now(timezone.utc) - last_timestamp).total_seconds()
        remaining = int(effective_state["cooldown_seconds"] - elapsed)
        return max(0, remaining)

    def _load_state(self) -> Dict[str, Any]:
        default_state = {
            "mode": self.config.scaling_mode,
            "scale_out_cpu_threshold": self.config.scale_out_cpu_threshold,
            "scale_in_cpu_threshold": self.config.scale_in_cpu_threshold,
            "min_instances": self.config.scaler_min_instances,
            "max_instances": self.config.scaler_max_instances,
            "cooldown_seconds": self.config.scaler_cooldown_seconds,
            "active_control": self.config.control_enabled,
            "last_action": "none",
            "last_action_at": None,
            "last_reason": "Controller initialised from configuration.",
            "latest_desired_capacity": None,
            "last_processed_cpu_timestamp": None,
        }

        if not self.config.controller_state_path.exists():
            self.state = default_state
            self._save_state()
            return default_state

        with self.config.controller_state_path.open("r", encoding="utf-8") as handle:
            stored_state = json.load(handle)

        merged = {**default_state, **stored_state}
        self._validate_state(merged)
        return merged

    def _save_state(self) -> None:
        with self.config.controller_state_path.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, indent=2)

    @staticmethod
    def _latest_series_timestamp(snapshot: Dict[str, Any], series_name: str) -> Optional[str]:
        series = snapshot.get("raw_series", {}).get(series_name) or []
        if not series:
            return None
        latest_point = series[-1]
        return latest_point.get("timestamp")

    @staticmethod
    def _recent_series_values(
        snapshot: Dict[str, Any],
        series_name: str,
        limit: int = 2,
    ) -> list[float]:
        series = snapshot.get("raw_series", {}).get(series_name) or []
        values = []
        for point in series:
            value = point.get("value")
            if value is None:
                continue
            values.append(float(value))
        return values[-limit:]

    @staticmethod
    def _series_matches_threshold(
        values: list[float],
        threshold: float,
        direction: str,
        required_samples: int = 2,
    ) -> bool:
        if len(values) < required_samples:
            return False
        if direction == "above":
            return all(value >= threshold for value in values[-required_samples:])
        return all(value <= threshold for value in values[-required_samples:])

    @staticmethod
    def _has_request_signal(
        current_request_count: Any,
        recent_request_values: list[float],
        minimum_request_threshold: float,
    ) -> bool:
        if current_request_count is not None and float(current_request_count) > minimum_request_threshold:
            return True
        return any(value > minimum_request_threshold for value in recent_request_values)

    @staticmethod
    def _all_request_values_below_threshold(
        current_request_count: Any,
        recent_request_values: list[float],
        threshold: float,
    ) -> bool:
        if current_request_count is not None and float(current_request_count) > threshold:
            return False
        return all(value <= threshold for value in recent_request_values)

    @staticmethod
    def _sample_phrase(sample_count: int) -> str:
        if sample_count == 1:
            return "the latest CPU sample"
        return f"{sample_count} consecutive CPU samples"

    @staticmethod
    def _build_noop_response(reason: str) -> Dict[str, Any]:
        return {
            "status": "noop",
            "action": "none",
            "desired_capacity": None,
            "reason": reason,
        }
