import asyncio

import pytest
from pyhap.accessory_driver import AccessoryDriver
from pyhap.util import is_callback

from hap_daikin_ac.rf_homekit import RfFanAccessory, RfLightToggleAccessory, percent_to_speed


class RecordingController:
    def __init__(self):
        self.commands = []
        self.error = None

    def send(self, command):
        self.commands.append(command)
        if self.error:
            raise self.error


@pytest.fixture
def controls(monkeypatch):
    loop = asyncio.new_event_loop()
    now = 0.0
    monkeypatch.setattr(loop, "time", lambda: now)
    driver = AccessoryDriver(
        address="127.0.0.1", port=0, persist_file="/tmp/hap-rf-fan-test.state",
        pincode=b"031-45-154", loop=loop,
    )
    driver.add_job = lambda target, *args: target(*args)
    controller = RecordingController()
    fan = RfFanAccessory(driver, "Fan", controller=controller)
    light = RfLightToggleAccessory(driver, "Light Toggle", controller=controller)

    def advance(seconds):
        nonlocal now
        now += seconds
        loop.run_until_complete(asyncio.sleep(0))

    try:
        yield controller, fan, light, advance
    finally:
        loop.run_until_complete(fan.stop())
        loop.run_until_complete(light.stop())
        loop.close()


@pytest.mark.parametrize("percent, speed", [(0, "off"), (1, "low"), (33, "low"), (34, "mid"), (66, "mid"), (67, "high"), (100, "high")])
def test_percent_maps_to_only_supported_speeds(percent, speed):
    assert percent_to_speed(percent) == speed


def test_startup_does_not_transmit(controls):
    controller, fan, light, _ = controls
    assert controller.commands == []
    assert fan.char_active.value == 0
    assert light.char_on.value is False


@pytest.mark.parametrize("percent, command", [(0, "fan_off"), (33, "fan_low"), (66, "fan_mid"), (100, "fan_high")])
def test_fan_controls_use_their_learned_commands(controls, percent, command):
    controller, fan, _, advance = controls
    fan.set_speed(percent)
    fan.handle_write({"RotationSpeed": percent})
    advance(0.3)
    assert controller.commands == [command]
    assert fan.char_speed.value == percent


def test_fan_slider_debounces_and_off_cancels_pending_speed(controls):
    controller, fan, _, advance = controls
    fan.set_active(1)
    fan.handle_write({"Active": 1})
    controller.commands.clear()
    for speed in [34, 66, 80, 100]:
        fan.set_speed(speed)
        fan.handle_write({"RotationSpeed": speed})
        advance(0.05)
    assert controller.commands == []
    advance(0.3)
    assert controller.commands == ["fan_high"]
    fan.set_speed(66)
    fan.handle_write({"RotationSpeed": 66})
    fan.set_active(0)
    fan.handle_write({"Active": 0})
    assert controller.commands == ["fan_high", "fan_off"]
    advance(1)
    assert controller.commands == ["fan_high", "fan_off"]


def test_explicit_off_wins_over_speed_in_a_batched_write(controls):
    controller, fan, _, _ = controls
    fan.set_active(0)
    fan.set_speed(100)
    fan.handle_write({"Active": 0, "RotationSpeed": 100})
    assert controller.commands == ["fan_off"]
    assert fan.char_active.value == 0


def test_power_on_restores_last_selected_speed(controls):
    controller, fan, _, _ = controls
    fan.set_speed(66)
    fan.handle_write({"RotationSpeed": 66})
    fan.set_active(0)
    fan.handle_write({"Active": 0})
    fan.set_active(1)
    fan.handle_write({"Active": 1})
    assert controller.commands == ["fan_mid", "fan_off", "fan_mid"]


def test_each_light_activation_sends_once_and_resets_switch(controls):
    controller, _, light, _ = controls
    light.char_on.client_update_value(True)
    assert light.char_on.value is False
    light.char_on.client_update_value(False)
    light.char_on.client_update_value(True)
    assert controller.commands == ["light_toggle", "light_toggle"]
    assert light.char_on.value is False


def test_light_failure_does_not_retry_or_change_fan(controls):
    controller, fan, light, _ = controls
    controller.error = RuntimeError("delivery uncertain")
    light.char_on.client_update_value(True)
    assert controller.commands == ["light_toggle"]
    assert light.char_on.value is False
    assert fan.speed == "off"


def test_shutdown_cancels_speed_and_ignores_light_activations(controls):
    controller, fan, light, advance = controls
    fan.set_active(1)
    fan.handle_write({"Active": 1})
    controller.commands.clear()
    fan.set_speed(100)
    fan.handle_write({"RotationSpeed": 100})
    fan.driver.loop.run_until_complete(fan.stop())
    fan.driver.loop.run_until_complete(light.stop())
    light.set_on(True)
    advance(1)
    assert controller.commands == []


def test_stale_executor_job_cannot_restart_fan_after_off(controls, monkeypatch):
    controller, fan, _, advance = controls
    jobs = []

    def add_job(target, *args):
        if is_callback(target):
            target(*args)
        else:
            jobs.append(lambda: target(*args))

    monkeypatch.setattr(fan.driver, "add_job", add_job)
    fan.set_active(1)
    fan.handle_write({"Active": 1})
    fan.set_active(0)
    fan.handle_write({"Active": 0})
    for job in reversed(jobs):
        job()
    advance(1)
    assert controller.commands == ["fan_off"]
