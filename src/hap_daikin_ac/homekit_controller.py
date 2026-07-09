"""Broadlink-backed Daikin controller used by HomeKit accessories."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from threading import Lock
import time
from typing import Any

from .broadlink_codec import format_hex, pulses_to_broadlink_packet
from .protocol import DaikinCommand, state_to_pulses
from .rm4 import (
    Rm4SensorReadings,
    authenticate_device,
    device_mac_hex,
    device_summary,
    read_device_sensors,
    select_device,
    send_ir_packet_to_device,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class BroadlinkTarget:
    host: str | None = None
    mac: str | None = None
    timeout: int = 5
    repeats: int = 1
    repeat_delay: float = 0.4
    local_ip_address: str | None = None
    discover_ip_address: str | None = None
    dry_run: bool = False
    sensor_cache_ttl: float = 60.0


class BroadlinkDaikinController:
    """Generate Daikin IR packets and send them via the configured RM4."""

    def __init__(self, target: BroadlinkTarget) -> None:
        self.target = target
        self._device: Any | None = None
        self._device_lock = Lock()
        self._sensor_cache: Rm4SensorReadings | None = None
        self._sensor_cache_at = 0.0

    def connect(self) -> None:
        """Resolve and authenticate the RM4 once for the HomeKit process."""
        if self.target.dry_run:
            LOGGER.info("dry-run mode; RM4 discovery is skipped")
            return
        if self._device is not None:
            return

        device = select_device(
            host=self.target.host,
            mac=self.target.mac,
            timeout=self.target.timeout,
            local_ip_address=self.target.local_ip_address,
            discover_ip_address=self.target.discover_ip_address,
        )
        authenticate_device(device)
        self._device = device
        LOGGER.info("bound RM4 controller to %s", device_summary(device))

    def send(self, command: DaikinCommand) -> None:
        state = command.to_state()
        packet = pulses_to_broadlink_packet(state_to_pulses(state))

        if self.target.dry_run:
            LOGGER.info("dry-run Broadlink packet: %s", format_hex(packet))
            return

        device = self._require_device()
        with self._device_lock:
            send_ir_packet_to_device(
                device,
                packet,
                repeats=self.target.repeats,
                repeat_delay=self.target.repeat_delay,
            )
        LOGGER.info("sent Daikin command via %s", device_summary(device))

    def _require_device(self) -> Any:
        if self._device is None:
            self.connect()
        if self._device is None:
            raise RuntimeError("RM4 controller is not connected")
        return self._device

    def read_sensors(self, *, force: bool = False) -> Rm4SensorReadings | None:
        if self.target.dry_run:
            LOGGER.info("dry-run sensor read skipped")
            return None

        now = time.monotonic()
        if (
            not force
            and self._sensor_cache is not None
            and now - self._sensor_cache_at < self.target.sensor_cache_ttl
        ):
            return self._sensor_cache

        device = self._require_device()
        with self._device_lock:
            readings = read_device_sensors(device)
        self._sensor_cache = readings
        self._sensor_cache_at = now
        return readings

    def device_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "rm4_configured_host": self.target.host,
            "rm4_configured_mac": self.target.mac,
        }
        if self._device is None:
            return _without_empty_values(metadata)

        host = getattr(self._device, "host", None)
        if isinstance(host, tuple):
            host = host[0]
        elif host is not None:
            host = str(host)
        metadata.update(
            {
                "rm4_host": host,
                "rm4_mac": device_mac_hex(self._device),
                "rm4_model": str(
                    getattr(self._device, "model", self._device.__class__.__name__)
                ),
            }
        )
        return _without_empty_values(metadata)


def _without_empty_values(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in values.items()
        if value is not None and value != ""
    }
