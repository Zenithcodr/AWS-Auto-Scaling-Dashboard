import csv
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import AppConfig


LOGGER = logging.getLogger(__name__)

METRIC_COLUMNS = [
    "timestamp",
    "average_cpu",
    "instance_count",
    "request_count",
    "healthy_host_count",
    "desired_capacity",
    "mode",
    "scale_out_cpu_threshold",
    "scale_in_cpu_threshold",
    "min_instances",
    "max_instances",
    "cooldown_seconds",
    "scaling_action",
    "load_balancer_arn",
    "auto_scaling_group_name",
]

EVENT_COLUMNS = [
    "timestamp",
    "event_source",
    "event_type",
    "action",
    "message",
    "mode",
    "desired_capacity",
    "result",
    "details",
]


class MetricsLogger:
    def __init__(self, config: AppConfig, aws_client: Optional[Any] = None):
        self.config = config
        self.aws_client = aws_client
        self._initialise_csv_file(self.config.metrics_csv_path, METRIC_COLUMNS)
        self._initialise_csv_file(self.config.events_csv_path, EVENT_COLUMNS)
        self._initialise_sqlite()

    def _get_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.config.sqlite_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise_csv_file(self, path: Path, headers: List[str]) -> None:
        if path.exists() and path.stat().st_size > 0:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writeheader()

    def _initialise_sqlite(self) -> None:
        with self._get_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics (
                    timestamp TEXT PRIMARY KEY,
                    average_cpu REAL,
                    instance_count INTEGER,
                    request_count REAL,
                    healthy_host_count REAL,
                    desired_capacity INTEGER,
                    mode TEXT,
                    scale_out_cpu_threshold REAL,
                    scale_in_cpu_threshold REAL,
                    min_instances INTEGER,
                    max_instances INTEGER,
                    cooldown_seconds INTEGER,
                    scaling_action TEXT,
                    load_balancer_arn TEXT,
                    auto_scaling_group_name TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    event_source TEXT,
                    event_type TEXT,
                    action TEXT,
                    message TEXT,
                    mode TEXT,
                    desired_capacity INTEGER,
                    result TEXT,
                    details TEXT
                )
                """
            )

    def _append_csv(self, path: Path, headers: List[str], record: Dict[str, Any]) -> None:
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers)
            writer.writerow({header: record.get(header, "") for header in headers})

    def _sync_to_s3(self) -> None:
        if not self.config.log_to_s3 or not self.aws_client or not self.config.s3_log_bucket:
            return

        upload_targets = [
            (self.config.metrics_csv_path, "autoscaling-dashboard/metrics.csv"),
            (self.config.events_csv_path, "autoscaling-dashboard/events.csv"),
            (self.config.sqlite_path, "autoscaling-dashboard/metrics.db"),
        ]
        for file_path, object_key in upload_targets:
            try:
                self.aws_client.upload_file_to_s3(
                    str(file_path),
                    bucket_name=self.config.s3_log_bucket,
                    key=object_key,
                )
            except Exception as exc:  # pylint: disable=broad-except
                LOGGER.warning("Unable to archive %s to S3: %s", file_path, exc)

    def log_metric(self, record: Dict[str, Any]) -> Dict[str, Any]:
        metric_record = {column: record.get(column, "") for column in METRIC_COLUMNS}
        metric_record["timestamp"] = metric_record.get("timestamp") or datetime.now(
            timezone.utc
        ).isoformat()

        self._append_csv(self.config.metrics_csv_path, METRIC_COLUMNS, metric_record)
        with self._get_connection() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO metrics (
                    timestamp, average_cpu, instance_count, request_count, healthy_host_count,
                    desired_capacity, mode, scale_out_cpu_threshold, scale_in_cpu_threshold,
                    min_instances, max_instances, cooldown_seconds, scaling_action,
                    load_balancer_arn, auto_scaling_group_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [metric_record[column] for column in METRIC_COLUMNS],
            )
        self._sync_to_s3()
        return metric_record

    def log_event(self, record: Dict[str, Any]) -> Dict[str, Any]:
        event_record = {column: record.get(column, "") for column in EVENT_COLUMNS}
        event_record["timestamp"] = event_record.get("timestamp") or datetime.now(
            timezone.utc
        ).isoformat()

        self._append_csv(self.config.events_csv_path, EVENT_COLUMNS, event_record)
        with self._get_connection() as connection:
            connection.execute(
                """
                INSERT INTO events (
                    timestamp, event_source, event_type, action, message,
                    mode, desired_capacity, result, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [event_record[column] for column in EVENT_COLUMNS],
            )
        self._sync_to_s3()
        return event_record

    def get_recent_metrics(self, limit: int = 120) -> List[Dict[str, Any]]:
        with self._get_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM metrics
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        results = [dict(row) for row in rows]
        return list(reversed(results))

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as connection:
            rows = connection.execute(
                """
                SELECT timestamp, event_source, event_type, action, message,
                       mode, desired_capacity, result, details
                FROM events
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]

    def get_latest_metric(self) -> Optional[Dict[str, Any]]:
        metrics = self.get_recent_metrics(limit=1)
        return metrics[-1] if metrics else None
