"""Secondary HomeKit accessories for fan speed and AC mode switches."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyhap.accessory import Accessory
from pyhap.const import CATEGORY_FAN, CATEGORY_SWITCH

from .homekit_common import (
    ACTIVE_ACTIVE,
    ACTIVE_INACTIVE,
    COMMAND_TRIGGER_CHARS,
    CURRENT_FAN_STATE_BLOWING_AIR,
    CURRENT_FAN_STATE_INACTIVE,
    SWING_DISABLED,
    SWING_ENABLED,
    TARGET_FAN_STATE_AUTO,
    TARGET_FAN_STATE_MANUAL,
    fan_to_rotation_speed,
)
from .protocol import Mode

if TYPE_CHECKING:
    from .homekit import DaikinAcAccessory


class DaikinFanAccessory(Accessory):
    """Separate HomeKit fan control surface for the Daikin AC."""

    category = CATEGORY_FAN

    def __init__(
        self,
        *args,
        ac_accessory: DaikinAcAccessory,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.ac_accessory = ac_accessory

        self.set_info_service(
            manufacturer="Daikin",
            model="IR AC fan controls via Broadlink RM4",
            serial_number="hap-daikin-ac-fan",
            firmware_revision="0.1.0",
        )

        service = self.add_preload_service(
            "Fanv2",
            chars=[
                "Name",
                "CurrentFanState",
                "TargetFanState",
                "RotationSpeed",
                "SwingMode",
            ],
        )
        service.setter_callback = self.handle_fan_write

        self.char_active = service.configure_char(
            "Active",
            value=ACTIVE_INACTIVE,
            setter_callback=self.set_active,
        )
        self.char_current_state = service.configure_char(
            "CurrentFanState",
            value=CURRENT_FAN_STATE_INACTIVE,
        )
        self.char_target_state = service.configure_char(
            "TargetFanState",
            value=TARGET_FAN_STATE_AUTO,
            setter_callback=self.set_target_fan_state,
        )
        self.char_rotation_speed = service.configure_char(
            "RotationSpeed",
            properties={"minValue": 0, "maxValue": 100, "minStep": 20},
            value=fan_to_rotation_speed(self.ac_accessory.fan),
            setter_callback=self.set_rotation_speed,
        )
        self.char_swing = service.configure_char(
            "SwingMode",
            value=SWING_DISABLED,
            setter_callback=self.set_swing,
        )
        service.configure_char("Name", value=self.display_name)

    def set_active(self, value: int) -> None:
        self.ac_accessory.set_active(value)
        self.update_from_ac()

    def set_target_fan_state(self, value: int) -> None:
        if value == TARGET_FAN_STATE_AUTO:
            self.ac_accessory.set_rotation_speed(0)
        elif self.ac_accessory.fan == "auto":
            self.ac_accessory.set_rotation_speed(60)
        self.update_from_ac()

    def set_rotation_speed(self, value: float) -> None:
        self.ac_accessory.set_rotation_speed(value)
        self.update_from_ac()

    def set_swing(self, value: int) -> None:
        self.ac_accessory.set_swing(value)
        self.update_from_ac()

    def handle_fan_write(self, chars: dict[str, object]) -> None:
        if not COMMAND_TRIGGER_CHARS.intersection(chars):
            return
        if not self.ac_accessory.active and "Active" not in chars:
            return
        self.ac_accessory._schedule_current_command()

    def update_from_ac(self, *, should_notify: bool = True) -> None:
        active = ACTIVE_ACTIVE if self.ac_accessory.active else ACTIVE_INACTIVE
        current_state = (
            CURRENT_FAN_STATE_BLOWING_AIR
            if self.ac_accessory.active
            else CURRENT_FAN_STATE_INACTIVE
        )
        target_state = (
            TARGET_FAN_STATE_MANUAL
            if self.ac_accessory.quiet_mode
            else (
                TARGET_FAN_STATE_AUTO
                if self.ac_accessory.fan == "auto"
                else TARGET_FAN_STATE_MANUAL
            )
        )
        self.char_active.set_value(active, should_notify=should_notify)
        self.char_current_state.set_value(current_state, should_notify=should_notify)
        self.char_target_state.set_value(target_state, should_notify=should_notify)
        self.char_rotation_speed.set_value(
            self.ac_accessory._display_rotation_speed(),
            should_notify=should_notify,
        )
        self.char_swing.set_value(
            SWING_ENABLED if self.ac_accessory.swing_vertical else SWING_DISABLED,
            should_notify=should_notify,
        )


class DaikinModeSwitchAccessory(Accessory):
    """HomeKit switch for a mutually-exclusive Daikin operating mode."""

    category = CATEGORY_SWITCH

    def __init__(
        self,
        *args,
        ac_accessory: DaikinAcAccessory,
        mode: Mode | str,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.ac_accessory = ac_accessory
        self.mode = Mode(str(mode).lower())
        if self.mode not in {Mode.DRY, Mode.FAN}:
            raise ValueError("mode switch must control dry or fan mode")

        self.set_info_service(
            manufacturer="Daikin",
            model="IR AC mode switch via Broadlink RM4",
            serial_number=f"hap-daikin-ac-{self.mode.value}-switch",
            firmware_revision="0.1.0",
        )

        service = self.add_preload_service("Switch", chars=["Name"])
        service.setter_callback = self.handle_switch_write
        self.char_on = service.configure_char(
            "On",
            value=False,
            setter_callback=self.set_on,
        )
        service.configure_char("Name", value=self.display_name)

    def set_on(self, value: bool) -> None:
        self.ac_accessory.set_mode_switch(self.mode, bool(value))
        self.update_from_ac()

    def handle_switch_write(self, chars: dict[str, object]) -> None:
        if "On" not in chars:
            return
        if not self.ac_accessory.active and not bool(chars["On"]):
            return
        self.ac_accessory._schedule_current_command()

    def update_from_ac(self, *, should_notify: bool = True) -> None:
        self.char_on.set_value(
            self.ac_accessory.active and self.ac_accessory.mode == self.mode,
            should_notify=should_notify,
        )


class DaikinQuietSwitchAccessory(Accessory):
    """HomeKit switch for Daikin quiet mode."""

    category = CATEGORY_SWITCH

    def __init__(
        self,
        *args,
        ac_accessory: DaikinAcAccessory,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.ac_accessory = ac_accessory

        self.set_info_service(
            manufacturer="Daikin",
            model="IR AC quiet switch via Broadlink RM4",
            serial_number="hap-daikin-ac-quiet-switch",
            firmware_revision="0.1.0",
        )

        service = self.add_preload_service("Switch", chars=["Name"])
        service.setter_callback = self.handle_switch_write
        self.char_on = service.configure_char(
            "On",
            value=False,
            setter_callback=self.set_on,
        )
        service.configure_char("Name", value=self.display_name)

    def set_on(self, value: bool) -> None:
        self.ac_accessory.set_quiet_mode(bool(value))
        self.update_from_ac()

    def handle_switch_write(self, chars: dict[str, object]) -> None:
        if "On" not in chars:
            return
        if not self.ac_accessory.active and not bool(chars["On"]):
            return
        self.ac_accessory._schedule_current_command()

    def update_from_ac(self, *, should_notify: bool = True) -> None:
        self.char_on.set_value(
            self.ac_accessory.active and self.ac_accessory.quiet_mode,
            should_notify=should_notify,
        )
