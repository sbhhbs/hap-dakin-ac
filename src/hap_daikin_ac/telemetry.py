"""Sensor telemetry delivery for external dashboards."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
import socket
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from .rm4 import Rm4SensorReadings

LOGGER = logging.getLogger(__name__)


class LogstashTelemetryClient:
    """POST RM4 sensor readings to a Logstash HTTP input."""

    def __init__(self, url: str | None, *, timeout: float = 3.0) -> None:
        self.url = normalize_logstash_url(url)
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return self.url is not None

    def send_sensor_reading(
        self,
        readings: Rm4SensorReadings,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return

        event = build_sensor_event(readings, metadata=metadata)
        data = json.dumps(event, sort_keys=True).encode("utf-8")
        http_request = request.Request(
            self.url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "hap-daikin-ac",
            },
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            LOGGER.warning("unable to publish RM4 sensor telemetry: %s", exc)


def build_sensor_event(
    readings: Rm4SensorReadings,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "service_name": "hap-daikin-ac",
        "container_hostname": socket.gethostname(),
        "event_type": "rm4_sensor_reading",
        "temperature_c": readings.temperature,
        "humidity_percent": readings.humidity,
    }
    if readings.raw:
        event["raw"] = readings.raw
    if metadata:
        event.update(_without_empty_values(metadata))
    return _without_empty_values(event)


def normalize_logstash_url(url: str | None) -> str | None:
    if url is None or not url.strip():
        return None
    normalized = url.strip()
    if urlparse(normalized).scheme not in {"http", "https"}:
        normalized = f"http://{normalized}"
    return normalized


def _without_empty_values(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if value is not None and value != ""
    }
