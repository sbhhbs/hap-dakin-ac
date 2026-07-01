"""HomeKit accessory for a Daikin cooling-only AC controlled by Broadlink."""

from __future__ import annotations

import asyncio
import logging
import math
from threading import Lock
import time
from dataclasses import dataclass
from typing import Any

from pyhap.accessory import Accessory
from pyhap.const import CATEGORY_AIR_CONDITIONER

from .broadlink_codec import format_hex, pulses_to_broadlink_packet
from .protocol import DaikinCommand, MAX_TEMP_C, MIN_TEMP_C, state_to_pulses
from .rm4 import (
    Rm4SensorReadings,
    authenticate_device,
    device_summary,
    read_device_sensors,
    select_device,
    send_ir_packet_to_device,
)

LOGGER = logging.getLogger(__name__)

ACTIVE_INACTIVE = 0
ACTIVE_ACTIVE = 1

CURRENT_STATE_INACTIVE = 0
CURRENT_STATE_COOLING = 3

TARGET_STATE_HEAT = 1
TARGET_STATE_COOL = 2

TEMP_DISPLAY_CELSIUS = 0
SWING_DISABLED = 0
SWING_ENABLED = 1

COMMAND_TRIGGER_CHARS = {
    "Active",
    "TargetHeaterCoolerState",
    "CoolingThresholdTemperature",
    "RotationSpeed",
    "SwingMode",
}


def rotation_speed_to_fan(value: float | int) -> int | str:
    """Map HomeKit RotationSpeed percentage to Daikin fan speed."""
    percent = max(0, min(100, float(value)))
    if percent <= 0:
        return "auto"
    return max(1, min(5, math.ceil(percent / 20)))


def fan_to_rotation_speed(fan: int | str) -> int:
    if isinstance(fan, str):
        normalized = fan.strip().lower()
        if normalized == "auto":
            return 0
        if normalized.isdecimal():
            return max(1, min(5, int(normalized))) * 20
        return 20
    return max(1, min(5, int(fan))) * 20


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


class DaikinAcAccessory(Accessory):
    """Cooling-only HomeKit AC accessory with fan speed control."""

    category = CATEGORY_AIR_CONDITIONER

    def __init__(
        self,
        *args,
        controller: BroadlinkDaikinController,
        initial_temp: int = 24,
        initial_fan: int | str = "auto",
        sensor_poll_interval: float = 60.0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.controller = controller
        self.active = False
        self.target_temp = int(max(MIN_TEMP_C, min(MAX_TEMP_C, initial_temp)))
        self.current_temp = float(self.target_temp)
        self.current_humidity = 0.0
        self.fan: int | str = initial_fan
        self.swing_vertical = False
        self.sensor_poll_interval = sensor_poll_interval

        self.set_info_service(
            manufacturer="Daikin",
            model="Cooling-only IR AC via Broadlink RM4",
            serial_number="hap-daikin-ac",
            firmware_revision="0.1.0",
        )

        service = self.add_preload_service(
            "HeaterCooler",
            chars=[
                "Name",
                "CoolingThresholdTemperature",
                "TemperatureDisplayUnits",
                "RotationSpeed",
                "SwingMode",
            ],
        )
        service.setter_callback = self.handle_hvac_write
        self.set_primary_service(service)

        self.char_active = service.configure_char(
            "Active",
            value=ACTIVE_INACTIVE,
            setter_callback=self.set_active,
        )
        self.char_current_state = service.configure_char(
            "CurrentHeaterCoolerState",
            value=CURRENT_STATE_INACTIVE,
        )
        self.char_target_state = service.configure_char(
            "TargetHeaterCoolerState",
            value=TARGET_STATE_COOL,
            setter_callback=self.set_target_state,
        )
        self.char_target_state.override_properties(
            valid_values={"Cool": TARGET_STATE_COOL}
        )
        self.char_target_state.allow_invalid_client_values = True

        self.char_current_temp = service.configure_char(
            "CurrentTemperature",
            properties={
                "minValue": MIN_TEMP_C,
                "maxValue": MAX_TEMP_C,
                "minStep": 1,
            },
            value=self.target_temp,
            getter_callback=self.get_current_temperature,
        )
        self.char_cooling_temp = service.configure_char(
            "CoolingThresholdTemperature",
            properties={
                "minValue": MIN_TEMP_C,
                "maxValue": MAX_TEMP_C,
                "minStep": 1,
            },
            value=self.target_temp,
            setter_callback=self.set_cooling_temperature,
        )
        self.char_temp_units = service.configure_char(
            "TemperatureDisplayUnits",
            value=TEMP_DISPLAY_CELSIUS,
        )
        self.char_rotation_speed = service.configure_char(
            "RotationSpeed",
            properties={"minValue": 0, "maxValue": 100, "minStep": 20},
            value=fan_to_rotation_speed(self.fan),
            setter_callback=self.set_rotation_speed,
        )
        self.char_swing = service.configure_char(
            "SwingMode",
            value=SWING_DISABLED,
            setter_callback=self.set_swing,
        )
        service.configure_char("Name", value=self.display_name)

        humidity_service = self.add_preload_service("HumiditySensor", chars=["Name"])
        self.char_current_humidity = humidity_service.configure_char(
            "CurrentRelativeHumidity",
            value=self.current_humidity,
            getter_callback=self.get_current_humidity,
        )
        humidity_service.configure_char("Name", value=f"{self.display_name} Humidity")

    async def run(self) -> None:
        if self.sensor_poll_interval <= 0:
            return

        while not self.driver.aio_stop_event.is_set():
            await self.driver.async_add_job(self.refresh_sensor_readings, True)
            try:
                await asyncio.wait_for(
                    self.driver.aio_stop_event.wait(),
                    timeout=self.sensor_poll_interval,
                )
            except TimeoutError:
                pass

    def set_active(self, value: int) -> None:
        self.active = value == ACTIVE_ACTIVE
        self._publish_state()

    def set_target_state(self, value: int) -> None:
        if value == TARGET_STATE_HEAT:
            self.char_target_state.set_value(TARGET_STATE_COOL, should_notify=True)
            raise ValueError("heat mode is not supported by this Daikin AC")

        # Some HomeKit clients, especially Siri, may request Auto even when it is
        # not advertised. This cooling-only accessory treats Auto as Cool.
        self.char_target_state.set_value(TARGET_STATE_COOL, should_notify=True)

    def set_cooling_temperature(self, value: float) -> None:
        self.target_temp = int(round(value))
        self.char_cooling_temp.set_value(self.target_temp, should_notify=True)

    def set_rotation_speed(self, value: float) -> None:
        self.fan = rotation_speed_to_fan(value)
        self.char_rotation_speed.set_value(
            fan_to_rotation_speed(self.fan),
            should_notify=True,
        )

    def set_swing(self, value: int) -> None:
        self.swing_vertical = value == SWING_ENABLED
        self.char_swing.set_value(
            SWING_ENABLED if self.swing_vertical else SWING_DISABLED,
            should_notify=True,
        )

    def get_current_temperature(self) -> float:
        return self.current_temp

    def get_current_humidity(self) -> float:
        return self.current_humidity

    def handle_hvac_write(self, chars: dict[str, object]) -> None:
        if not COMMAND_TRIGGER_CHARS.intersection(chars):
            return
        if not self.active and "Active" not in chars:
            return
        self._schedule_current_command()

    def refresh_sensor_readings(self, notify: bool = True) -> None:
        try:
            readings = self.controller.read_sensors()
        except RuntimeError as exc:
            LOGGER.warning("unable to read RM4 sensors: %s", exc)
            return
        if readings is None:
            return

        if readings.temperature is not None:
            self.current_temp = readings.temperature
            self.char_current_temp.set_value(self.current_temp, should_notify=notify)
        if readings.humidity is not None:
            self.current_humidity = readings.humidity
            self.char_current_humidity.set_value(
                self.current_humidity,
                should_notify=notify,
            )

    def _publish_state(self) -> None:
        self.char_active.set_value(
            ACTIVE_ACTIVE if self.active else ACTIVE_INACTIVE,
            should_notify=True,
        )
        self.char_current_state.set_value(
            CURRENT_STATE_COOLING if self.active else CURRENT_STATE_INACTIVE,
            should_notify=True,
        )
        self.char_target_state.set_value(TARGET_STATE_COOL, should_notify=True)

    def _schedule_current_command(self) -> None:
        command = DaikinCommand(
            power=self.active,
            mode="cool",
            temp_c=self.target_temp,
            fan=self.fan,
            swing_vertical=self.swing_vertical,
        )
        self.driver.add_job(self._send_command, command)

    def _send_command(self, command: DaikinCommand) -> None:
        try:
            self.controller.send(command)
        except RuntimeError as exc:
            LOGGER.warning("unable to send Daikin command: %s", exc)
