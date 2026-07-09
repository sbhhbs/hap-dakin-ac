"""Shared HomeKit constants and fan-speed conversion helpers."""

from __future__ import annotations

import math

ACTIVE_INACTIVE = 0
ACTIVE_ACTIVE = 1

CURRENT_STATE_INACTIVE = 0
CURRENT_STATE_IDLE = 1
CURRENT_STATE_COOLING = 3

TARGET_STATE_HEAT = 1
TARGET_STATE_COOL = 2

TEMP_DISPLAY_CELSIUS = 0
SWING_DISABLED = 0
SWING_ENABLED = 1
CURRENT_FAN_STATE_INACTIVE = 0
CURRENT_FAN_STATE_BLOWING_AIR = 2
TARGET_FAN_STATE_MANUAL = 0
TARGET_FAN_STATE_AUTO = 1

AUTO_ROTATION_SPEED = 64
QUIET_ROTATION_SPEED = 17

COMMAND_TRIGGER_CHARS = {
    "Active",
    "TargetFanState",
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
            return AUTO_ROTATION_SPEED
        if normalized in {"quiet", "silent"}:
            return QUIET_ROTATION_SPEED
        if normalized.isdecimal():
            return max(1, min(5, int(normalized))) * 20
        return 20
    return max(1, min(5, int(fan))) * 20


def set_rotation_speed_display(
    characteristic: object,
    value: int,
    *,
    should_notify: bool = True,
) -> None:
    """Publish display-only RotationSpeed values without minStep rounding."""
    changed = characteristic.value != value
    characteristic.value = value
    if changed and should_notify and characteristic.broker:
        characteristic.notify()
