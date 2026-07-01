"""HomeKit accessory for a Daikin cooling-only AC controlled by Broadlink."""

from __future__ import annotations

import asyncio
import logging

from pyhap.accessory import Accessory
from pyhap.const import CATEGORY_AIR_CONDITIONER

from .homekit_common import (
    ACTIVE_ACTIVE,
    ACTIVE_INACTIVE,
    COMMAND_TRIGGER_CHARS,
    CURRENT_STATE_COOLING,
    CURRENT_STATE_IDLE,
    CURRENT_STATE_INACTIVE,
    SWING_DISABLED,
    SWING_ENABLED,
    TARGET_STATE_COOL,
    TARGET_STATE_HEAT,
    TEMP_DISPLAY_CELSIUS,
    fan_to_rotation_speed,
    rotation_speed_to_fan,
)
from .homekit_controller import BroadlinkDaikinController, BroadlinkTarget
from .homekit_controls import (
    DaikinFanAccessory,
    DaikinModeSwitchAccessory,
    DaikinQuietSwitchAccessory,
)
from .protocol import DaikinCommand, MAX_TEMP_C, MIN_TEMP_C, Mode

LOGGER = logging.getLogger(__name__)


class DaikinAcAccessory(Accessory):
    """Cooling-only HomeKit AC accessory with fan speed control."""

    category = CATEGORY_AIR_CONDITIONER

    def __init__(
        self,
        *args,
        controller: BroadlinkDaikinController,
        initial_temp: int = 24,
        min_temp: int = MIN_TEMP_C,
        max_temp: int = MAX_TEMP_C,
        initial_fan: int | str = "auto",
        sensor_poll_interval: float = 60.0,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        validate_temperature_limits(min_temp, max_temp)
        self.controller = controller
        self.active = False
        self.min_temp = int(min_temp)
        self.max_temp = int(max_temp)
        self.target_temp = self._clamp_temp(initial_temp)
        self.current_temp = float(self.target_temp)
        self.current_humidity = 0.0
        self.mode = Mode.COOL
        self.fan: int | str = initial_fan
        self.swing_vertical = False
        self.quiet_mode = False
        self.sensor_poll_interval = sensor_poll_interval
        self.fan_accessory: DaikinFanAccessory | None = None
        self.mode_switch_accessories: list[DaikinModeSwitchAccessory] = []
        self.quiet_switch_accessory: DaikinQuietSwitchAccessory | None = None

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
                "minValue": self.min_temp,
                "maxValue": self.max_temp,
                "minStep": 1,
            },
            value=self.target_temp,
            getter_callback=self.get_current_temperature,
        )
        self.char_cooling_temp = service.configure_char(
            "CoolingThresholdTemperature",
            properties={
                "minValue": self.min_temp,
                "maxValue": self.max_temp,
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
            value=self._display_rotation_speed(),
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

    def register_fan_accessory(self, fan_accessory: "DaikinFanAccessory") -> None:
        self.fan_accessory = fan_accessory
        fan_accessory.update_from_ac(should_notify=False)

    def register_mode_switch_accessory(
        self,
        mode_switch_accessory: "DaikinModeSwitchAccessory",
    ) -> None:
        self.mode_switch_accessories.append(mode_switch_accessory)
        mode_switch_accessory.update_from_ac(should_notify=False)

    def register_quiet_switch_accessory(
        self,
        quiet_switch_accessory: "DaikinQuietSwitchAccessory",
    ) -> None:
        self.quiet_switch_accessory = quiet_switch_accessory
        quiet_switch_accessory.update_from_ac(should_notify=False)

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
        if not self.active:
            self.mode = Mode.COOL
            self.quiet_mode = False
        self._publish_state()

    def set_target_state(self, value: int) -> None:
        if value == TARGET_STATE_HEAT:
            self.char_target_state.set_value(TARGET_STATE_COOL, should_notify=True)
            raise ValueError("heat mode is not supported by this Daikin AC")

        # Some HomeKit clients, especially Siri, may request Auto even when it is
        # not advertised. This cooling-only accessory treats Auto as Cool.
        self.mode = Mode.COOL
        self.char_target_state.set_value(TARGET_STATE_COOL, should_notify=True)
        self._sync_linked_accessories()

    def set_cooling_temperature(self, value: float) -> None:
        self.target_temp = self._clamp_temp(value)
        self.char_cooling_temp.set_value(self.target_temp, should_notify=True)

    def set_rotation_speed(self, value: float) -> None:
        self.quiet_mode = False
        self.fan = rotation_speed_to_fan(value)
        self.char_rotation_speed.set_value(
            self._display_rotation_speed(),
            should_notify=True,
        )
        self._sync_linked_accessories()

    def set_swing(self, value: int) -> None:
        self.swing_vertical = value == SWING_ENABLED
        self.char_swing.set_value(
            SWING_ENABLED if self.swing_vertical else SWING_DISABLED,
            should_notify=True,
        )
        self._sync_linked_accessories()

    def set_mode_switch(self, mode: Mode | str, enabled: bool) -> None:
        mode = Mode(str(mode).lower())
        if mode not in {Mode.DRY, Mode.FAN}:
            raise ValueError("mode switch must control dry or fan mode")

        if enabled:
            self.active = True
            self.mode = mode
        elif self.mode == mode:
            self.mode = Mode.COOL
        self._publish_state()

    def set_quiet_mode(self, enabled: bool) -> None:
        self.quiet_mode = bool(enabled)
        if self.quiet_mode:
            self.active = True
        self._publish_state()

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
            self._current_heater_cooler_state(),
            should_notify=True,
        )
        self.char_target_state.set_value(TARGET_STATE_COOL, should_notify=True)
        self.char_rotation_speed.set_value(
            self._display_rotation_speed(),
            should_notify=True,
        )
        self._sync_linked_accessories()

    def _current_heater_cooler_state(self) -> int:
        if not self.active:
            return CURRENT_STATE_INACTIVE
        if self.mode in {Mode.COOL, Mode.DRY}:
            return CURRENT_STATE_COOLING
        return CURRENT_STATE_IDLE

    def _schedule_current_command(self) -> None:
        command = DaikinCommand(
            power=self.active,
            mode=self.mode,
            temp_c=self.target_temp,
            fan=self._command_fan(),
            swing_vertical=self.swing_vertical,
            quiet_mode=self.quiet_mode,
        )
        self.driver.add_job(self._send_command, command)

    def _display_rotation_speed(self) -> int:
        if self.quiet_mode:
            return 0
        return fan_to_rotation_speed(self.fan)

    def _command_fan(self) -> int | str:
        if self.quiet_mode:
            return "quiet"
        return self.fan

    def _clamp_temp(self, value: float | int) -> int:
        return int(max(self.min_temp, min(self.max_temp, round(value))))

    def _send_command(self, command: DaikinCommand) -> None:
        try:
            self.controller.send(command)
        except RuntimeError as exc:
            LOGGER.warning("unable to send Daikin command: %s", exc)

    def _sync_linked_accessories(self) -> None:
        if self.fan_accessory is not None:
            self.fan_accessory.update_from_ac()
        for mode_switch_accessory in self.mode_switch_accessories:
            mode_switch_accessory.update_from_ac()
        if self.quiet_switch_accessory is not None:
            self.quiet_switch_accessory.update_from_ac()


def validate_temperature_limits(min_temp: int, max_temp: int) -> None:
    if min_temp < MIN_TEMP_C or max_temp > MAX_TEMP_C:
        raise ValueError(
            f"temperature limits must stay within Daikin range "
            f"{MIN_TEMP_C}..{MAX_TEMP_C} C"
        )
    if min_temp > max_temp:
        raise ValueError("minimum temperature cannot be greater than maximum temperature")
