"""HomeKit controls for a learned three-speed RF fan and toggle-only light."""

from __future__ import annotations

import asyncio
import logging
from threading import Lock

from pyhap.accessory import Accessory
from pyhap.accessory_driver import AccessoryDriver
from pyhap.const import CATEGORY_FAN, CATEGORY_SWITCH
from pyhap.util import callback
from zeroconf.asyncio import AsyncZeroconf

from .rf import RfController

LOGGER = logging.getLogger(__name__)
SPEED_PERCENT = {"off": 0, "low": 33, "mid": 66, "high": 100}


class _GracefulZeroconf(AsyncZeroconf):
    async def async_unregister_service(self, info):
        # Zeroconf returns a goodbye-broadcast task. HAP 5 otherwise closes its
        # loop before that task finishes, leaving it pending during shutdown.
        goodbye = await super().async_unregister_service(info)
        await goodbye


class RfAccessoryDriver(AccessoryDriver):
    async def async_start(self):
        if self.advertiser is None:
            options = {}
            if self.interface_choice is not None:
                options["interfaces"] = self.interface_choice
            self.advertiser = _GracefulZeroconf(**options)
        await super().async_start()


def percent_to_speed(value: float) -> str:
    value = max(0, min(100, float(value)))
    if value == 0:
        return "off"
    if value <= 33:
        return "low"
    return "mid" if value <= 66 else "high"


class RfFanAccessory(Accessory):
    category = CATEGORY_FAN

    def __init__(self, *args, controller: RfController, serial: str = "rf-fan", **kwargs):
        super().__init__(*args, **kwargs)
        self.controller = controller
        self.speed = "off"
        self.last_speed = "low"
        self._requested_speed = "off"
        self._pending: asyncio.TimerHandle | None = None
        self._generation = 0
        self._stopped = False
        self._send_lock = Lock()
        self.set_info_service(
            manufacturer="Learned RF", model="Three-speed RF fan",
            serial_number=serial, firmware_revision="0.1.0",
        )
        service = self.add_preload_service(
            "Fanv2", chars=["Name", "RotationSpeed", "CurrentFanState"]
        )
        service.setter_callback = self.handle_write
        self.set_primary_service(service)
        self.char_active = service.configure_char("Active", value=0, setter_callback=self.set_active)
        self.char_speed = service.configure_char(
            "RotationSpeed", value=0,
            properties={"minValue": 0, "maxValue": 100, "minStep": 1},
            setter_callback=self.set_speed,
        )
        self.char_state = service.configure_char("CurrentFanState", value=0)
        service.configure_char("Name", value=self.display_name)

    def set_active(self, value: int) -> None:
        self.speed = self.last_speed if value else "off"
        self._publish()

    def set_speed(self, value: float) -> None:
        self.speed = percent_to_speed(value)
        if self.speed != "off":
            self.last_speed = self.speed
        self._publish()

    def _publish(self) -> None:
        self.char_active.set_value(int(self.speed != "off"), should_notify=True)
        self.char_speed.set_value(SPEED_PERCENT[self.speed], should_notify=True)
        self.char_state.set_value(2 if self.speed != "off" else 0, should_notify=True)

    def handle_write(self, chars: dict[str, object]) -> None:
        if not {"Active", "RotationSpeed"}.intersection(chars):
            return
        # Explicit off wins regardless of the ordering of a batched write.
        if "Active" in chars and not chars["Active"]:
            self.set_active(0)
        self.driver.add_job(self._queue, self.speed, "RotationSpeed" in chars)

    @callback
    def _queue(self, speed: str, debounce: bool) -> None:
        if self._pending:
            self._pending.cancel()
            self._pending = None
        self._generation += 1
        if self._stopped or self.driver.stop_event.is_set():
            return
        power_changed = (speed == "off") != (self._requested_speed == "off")
        self._requested_speed = speed
        if debounce and speed != "off" and not power_changed:
            self._pending = self.driver.loop.call_later(0.3, self._dispatch, speed, self._generation)
        else:
            self._dispatch(speed, self._generation)

    @callback
    def _dispatch(self, speed: str, generation: int) -> None:
        self._pending = None
        self.driver.add_job(self._send, speed, generation)

    def _send(self, speed: str, generation: int) -> None:
        with self._send_lock:
            if self._stopped or self.driver.stop_event.is_set() or generation != self._generation:
                return
            try:
                self.controller.send(f"fan_{speed}")
            except RuntimeError as exc:
                LOGGER.warning("unable to control RF fan: %s", exc)

    async def stop(self) -> None:
        self._stopped = True
        self._generation += 1
        if self._pending:
            self._pending.cancel()
            self._pending = None


class RfLightToggleAccessory(Accessory):
    """Momentary switch: each true write sends exactly one toggle request."""

    category = CATEGORY_SWITCH

    def __init__(self, *args, controller: RfController, serial: str = "rf-light", **kwargs):
        super().__init__(*args, **kwargs)
        self.controller = controller
        self._stopped = False
        self.set_info_service(
            manufacturer="Learned RF", model="Momentary light toggle",
            serial_number=serial, firmware_revision="0.1.0",
        )
        service = self.add_preload_service("Switch", chars=["Name"])
        self.set_primary_service(service)
        self.char_on = service.configure_char("On", value=False, setter_callback=self.set_on)
        service.configure_char("Name", value=self.display_name)

    def set_on(self, value: bool) -> None:
        if value and not self._stopped:
            self.driver.add_job(self._toggle)

    def _toggle(self) -> None:
        try:
            if not self._stopped and not self.driver.stop_event.is_set():
                self.controller.send("light_toggle")
        except RuntimeError as exc:
            LOGGER.warning("unable to toggle RF light: %s", exc)
        finally:
            self.driver.add_job(self._reset)

    @callback
    def _reset(self) -> None:
        self.char_on.set_value(False, should_notify=True)

    async def stop(self) -> None:
        self._stopped = True
        self._reset()
