import asyncio

import pytest

from pyhap.accessory_driver import AccessoryDriver
from pyhap.util import is_callback

from hap_daikin_ac.homekit import (
    BroadlinkDaikinController,
    BroadlinkTarget,
    DaikinAcAccessory,
    DaikinFanAccessory,
    DaikinModeSwitchAccessory,
    DaikinQuietSwitchAccessory,
    fan_to_rotation_speed,
    rotation_speed_to_fan,
)
from hap_daikin_ac.protocol import DaikinCommand, Mode
from hap_daikin_ac.rm4 import Rm4SensorReadings


def test_rotation_speed_zero_uses_auto_fan() -> None:
    assert rotation_speed_to_fan(0) == "auto"


def test_rotation_speed_maps_to_five_daikin_speeds() -> None:
    assert rotation_speed_to_fan(1) == 1
    assert rotation_speed_to_fan(20) == 1
    assert rotation_speed_to_fan(21) == 2
    assert rotation_speed_to_fan(80) == 4
    assert rotation_speed_to_fan(100) == 5


def test_fan_to_rotation_speed() -> None:
    assert fan_to_rotation_speed("auto") == 64
    assert fan_to_rotation_speed("quiet") == 17
    assert fan_to_rotation_speed("5") == 100
    assert fan_to_rotation_speed(1) == 20
    assert fan_to_rotation_speed(5) == 100


class FakeSensorController(BroadlinkDaikinController):
    def __init__(self) -> None:
        super().__init__(BroadlinkTarget(dry_run=True))
        self.read_count = 0

    def read_sensors(self, *, force: bool = False) -> Rm4SensorReadings:
        self.read_count += 1
        return Rm4SensorReadings(temperature=26.4, humidity=61.2, raw={})


class EmptySensorController(FakeSensorController):
    def read_sensors(self, *, force: bool = False) -> Rm4SensorReadings:
        self.read_count += 1
        return Rm4SensorReadings(temperature=None, humidity=None, raw={})


class RecordingController(BroadlinkDaikinController):
    def __init__(self) -> None:
        super().__init__(BroadlinkTarget(dry_run=True))
        self.commands: list[DaikinCommand] = []

    def send(self, command: DaikinCommand) -> None:
        self.commands.append(command)


@pytest.fixture
def debounce_controls(monkeypatch):
    """Use real asyncio timers with a virtual clock and synchronous IR recorder."""
    loop = asyncio.new_event_loop()
    now = 0.0
    monkeypatch.setattr(loop, "time", lambda: now)
    controller = RecordingController()
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
        loop=loop,
    )
    driver.add_job = lambda target, *args: target(*args)
    ac = DaikinAcAccessory(
        driver, "Test AC", controller=controller, sensor_poll_interval=0
    )
    fan = DaikinFanAccessory(driver, "Test Fan", ac_accessory=ac)
    ac.register_fan_accessory(fan)
    ac.set_active(1)
    ac.handle_hvac_write({"Active": 1})
    controller.commands.clear()

    def advance(seconds):
        nonlocal now
        now += seconds
        loop.run_until_complete(asyncio.sleep(0))

    try:
        yield controller, ac, fan, advance
    finally:
        loop.run_until_complete(ac.stop())
        loop.close()


class RecordingTelemetry:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[Rm4SensorReadings, dict[str, object]]] = []

    def send_sensor_reading(
        self,
        readings: Rm4SensorReadings,
        *,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.calls.append((readings, metadata or {}))


def test_homekit_sensor_readings_update_characteristics() -> None:
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=FakeSensorController(),
        sensor_poll_interval=0,
    )
    driver.add_accessory(accessory)

    accessory.refresh_sensor_readings(notify=False)

    assert accessory.char_current_temp.value == 26
    assert accessory.char_current_humidity.value == 61


def test_homekit_sensor_readings_publish_telemetry() -> None:
    controller = FakeSensorController()
    controller.device_metadata = lambda: {
        "rm4_host": "192.168.1.50",
        "rm4_mac": "a043b0b9f7f6",
    }
    telemetry = RecordingTelemetry()
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=controller,
        sensor_poll_interval=0,
        telemetry_client=telemetry,
        telemetry_context={"homekit_port": 51234},
    )
    driver.add_accessory(accessory)

    accessory.refresh_sensor_readings(notify=False)

    readings, metadata = telemetry.calls[0]
    assert readings.temperature == 26.4
    assert readings.humidity == 61.2
    assert metadata == {
        "accessory_name": "Test AC",
        "homekit_port": 51234,
        "rm4_host": "192.168.1.50",
        "rm4_mac": "a043b0b9f7f6",
    }


def test_homekit_sensor_telemetry_skips_empty_readings() -> None:
    telemetry = RecordingTelemetry()
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=EmptySensorController(),
        sensor_poll_interval=0,
        telemetry_client=telemetry,
    )
    driver.add_accessory(accessory)

    accessory.refresh_sensor_readings(notify=False)

    assert telemetry.calls == []


def test_homekit_getters_return_cached_sensor_values_without_io() -> None:
    controller = FakeSensorController()
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=controller,
        sensor_poll_interval=0,
    )
    driver.add_accessory(accessory)
    accessory.current_temp = 25.6
    accessory.current_humidity = 58.2

    assert accessory.get_current_temperature() == 25.6
    assert accessory.get_current_humidity() == 58.2
    assert controller.read_count == 0


def test_homekit_write_coalesces_single_async_send() -> None:
    controller = RecordingController()
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    driver.add_job = lambda target, *args: target(*args)
    accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=controller,
        sensor_poll_interval=0,
    )
    driver.add_accessory(accessory)

    accessory.set_active(1)
    accessory.set_cooling_temperature(23)
    accessory.set_rotation_speed(100)
    accessory.handle_hvac_write(
        {
            "Active": 1,
            "CoolingThresholdTemperature": 23,
            "RotationSpeed": 100,
        }
    )

    assert len(controller.commands) == 1
    command = controller.commands[0]
    assert command.power is True
    assert command.temp_c == 23
    assert command.fan == 5


def test_homekit_temperature_range_is_configurable() -> None:
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=RecordingController(),
        initial_temp=16,
        min_temp=18,
        max_temp=28,
        sensor_poll_interval=0,
    )

    assert accessory.target_temp == 18
    assert accessory.char_current_temp.properties["minValue"] == 18
    assert accessory.char_current_temp.properties["maxValue"] == 28
    assert accessory.char_cooling_temp.properties["minValue"] == 18
    assert accessory.char_cooling_temp.properties["maxValue"] == 28

    accessory.set_cooling_temperature(30)

    assert accessory.target_temp == 28
    assert accessory.char_cooling_temp.value == 28


def test_homekit_temperature_range_must_fit_daikin_protocol() -> None:
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )

    with pytest.raises(ValueError, match="temperature limits"):
        DaikinAcAccessory(
            driver,
            "Test AC",
            controller=RecordingController(),
            min_temp=5,
            max_temp=28,
            sensor_poll_interval=0,
        )

    with pytest.raises(ValueError, match="minimum temperature"):
        DaikinAcAccessory(
            driver,
            "Test AC",
            controller=RecordingController(),
            min_temp=28,
            max_temp=18,
            sensor_poll_interval=0,
        )


def test_fan_accessory_controls_shared_ac_state() -> None:
    controller = RecordingController()
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    driver.add_job = lambda target, *args: target(*args)
    ac_accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=controller,
        sensor_poll_interval=0,
    )
    fan_accessory = DaikinFanAccessory(
        driver,
        "Test AC Fan",
        ac_accessory=ac_accessory,
    )
    ac_accessory.register_fan_accessory(fan_accessory)
    driver.add_accessory(ac_accessory)

    fan_accessory.set_active(1)
    fan_accessory.set_target_fan_state(0)
    fan_accessory.set_rotation_speed(80)
    fan_accessory.set_swing(1)
    fan_accessory.handle_fan_write(
        {
            "Active": 1,
            "TargetFanState": 0,
            "RotationSpeed": 80,
            "SwingMode": 1,
        }
    )

    assert ac_accessory.active is True
    assert ac_accessory.fan == 4
    assert ac_accessory.swing_vertical is True
    assert fan_accessory.char_active.value == 1
    assert fan_accessory.char_rotation_speed.value == 80
    assert len(controller.commands) == 1


def test_auto_fan_displays_distinct_rotation_speed() -> None:
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    ac_accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=RecordingController(),
        sensor_poll_interval=0,
    )
    fan_accessory = DaikinFanAccessory(
        driver,
        "Test AC Fan",
        ac_accessory=ac_accessory,
    )
    ac_accessory.register_fan_accessory(fan_accessory)

    assert ac_accessory.char_rotation_speed.value == 64
    assert fan_accessory.char_rotation_speed.value == 64
    assert ac_accessory.char_rotation_speed.properties["minStep"] == 20
    assert fan_accessory.char_rotation_speed.properties["minStep"] == 20


def test_mode_switches_are_mutually_exclusive_and_default_to_cool() -> None:
    controller = RecordingController()
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    driver.add_job = lambda target, *args: target(*args)
    ac_accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=controller,
        sensor_poll_interval=0,
    )
    dry_switch = DaikinModeSwitchAccessory(
        driver,
        "Test AC Dry Mode",
        ac_accessory=ac_accessory,
        mode=Mode.DRY,
    )
    fan_mode_switch = DaikinModeSwitchAccessory(
        driver,
        "Test AC Fan Mode",
        ac_accessory=ac_accessory,
        mode=Mode.FAN,
    )
    ac_accessory.register_mode_switch_accessory(dry_switch)
    ac_accessory.register_mode_switch_accessory(fan_mode_switch)

    dry_switch.set_on(True)
    dry_switch.handle_switch_write({"On": True})
    fan_mode_switch.set_on(True)
    fan_mode_switch.handle_switch_write({"On": True})
    fan_mode_switch.set_on(False)
    fan_mode_switch.handle_switch_write({"On": False})

    assert ac_accessory.active is True
    assert ac_accessory.mode == Mode.COOL
    assert dry_switch.char_on.value is False
    assert fan_mode_switch.char_on.value is False
    assert [command.mode for command in controller.commands] == [
        Mode.DRY,
        Mode.FAN,
        Mode.COOL,
    ]
    assert all(command.power for command in controller.commands)


def test_fan_off_powers_off_ac_and_clears_mode_switches() -> None:
    controller = RecordingController()
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    driver.add_job = lambda target, *args: target(*args)
    ac_accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=controller,
        sensor_poll_interval=0,
    )
    fan_accessory = DaikinFanAccessory(
        driver,
        "Test AC Fan",
        ac_accessory=ac_accessory,
    )
    dry_switch = DaikinModeSwitchAccessory(
        driver,
        "Test AC Dry Mode",
        ac_accessory=ac_accessory,
        mode=Mode.DRY,
    )
    ac_accessory.register_fan_accessory(fan_accessory)
    ac_accessory.register_mode_switch_accessory(dry_switch)

    dry_switch.set_on(True)
    dry_switch.handle_switch_write({"On": True})
    fan_accessory.set_active(0)
    fan_accessory.handle_fan_write({"Active": 0})

    assert ac_accessory.active is False
    assert ac_accessory.mode == Mode.COOL
    assert fan_accessory.char_active.value == 0
    assert dry_switch.char_on.value is False
    assert controller.commands[-1].power is False
    assert controller.commands[-1].mode == Mode.COOL


def test_quiet_switch_updates_shared_command_state() -> None:
    controller = RecordingController()
    driver = AccessoryDriver(
        address="127.0.0.1",
        port=0,
        persist_file="/tmp/hap-daikin-test.state",
        pincode=b"031-45-154",
    )
    driver.add_job = lambda target, *args: target(*args)
    ac_accessory = DaikinAcAccessory(
        driver,
        "Test AC",
        controller=controller,
        sensor_poll_interval=0,
    )
    fan_accessory = DaikinFanAccessory(
        driver,
        "Test AC Fan",
        ac_accessory=ac_accessory,
    )
    quiet_switch = DaikinQuietSwitchAccessory(
        driver,
        "Test AC Quiet Mode",
        ac_accessory=ac_accessory,
    )
    ac_accessory.register_fan_accessory(fan_accessory)
    ac_accessory.register_quiet_switch_accessory(quiet_switch)
    ac_accessory.set_rotation_speed(80)

    quiet_switch.set_on(True)
    quiet_switch.handle_switch_write({"On": True})
    assert ac_accessory.char_rotation_speed.value == 17
    assert fan_accessory.char_rotation_speed.value == 17

    ac_accessory.set_active(0)
    ac_accessory.handle_hvac_write({"Active": 0})

    assert controller.commands[0].quiet_mode is True
    assert controller.commands[0].fan == "quiet"
    assert controller.commands[0].power is True
    assert controller.commands[-1].quiet_mode is False
    assert controller.commands[-1].power is False
    assert quiet_switch.char_on.value is False


def test_manual_fan_speed_clears_quiet_mode(debounce_controls) -> None:
    controller, ac_accessory, fan_accessory, advance = debounce_controls
    driver = ac_accessory.driver
    quiet_switch = DaikinQuietSwitchAccessory(
        driver,
        "Test AC Quiet Mode",
        ac_accessory=ac_accessory,
    )
    ac_accessory.register_fan_accessory(fan_accessory)
    ac_accessory.register_quiet_switch_accessory(quiet_switch)

    quiet_switch.set_on(True)
    quiet_switch.handle_switch_write({"On": True})
    fan_accessory.set_rotation_speed(80)
    fan_accessory.handle_fan_write({"RotationSpeed": 80})

    assert ac_accessory.active is True
    assert ac_accessory.quiet_mode is False
    assert ac_accessory.fan == 4
    assert ac_accessory.char_rotation_speed.value == 80
    assert fan_accessory.char_rotation_speed.value == 80
    assert quiet_switch.char_on.value is False
    assert controller.commands[-1].quiet_mode is True
    advance(0.3)
    assert controller.commands[-1].fan == 4
    assert controller.commands[-1].quiet_mode is False


@pytest.mark.parametrize("surface", ["ac", "fan", "mixed"])
@pytest.mark.parametrize("include_active", [False, True])
def test_fan_drag_sends_final_speed_after_pause(
    debounce_controls, surface, include_active
) -> None:
    controller, ac, fan, advance = debounce_controls
    for index, speed in enumerate([20, 40, 60, 80, 100]):
        if index:
            advance(0.05)
        control = ac if surface == "ac" or (surface == "mixed" and index % 2) else fan
        control.set_rotation_speed(speed)
        chars = {"RotationSpeed": speed}
        if include_active:
            control.set_active(1)
            chars["Active"] = 1
        if control is ac:
            ac.handle_hvac_write(chars)
        else:
            fan.handle_fan_write(chars)

    assert ac.char_rotation_speed.value == 100
    assert fan.char_rotation_speed.value == 100
    advance(0.299)
    assert controller.commands == []
    advance(0.002)
    assert len(controller.commands) == 1
    assert controller.commands[0].fan == 5


@pytest.mark.parametrize("include_active", [False, True])
def test_temperature_drag_sends_final_temperature_after_pause(
    debounce_controls, include_active
) -> None:
    controller, ac, _, advance = debounce_controls
    for temp in [23, 24, 25, 26, 27]:
        advance(0.05)
        ac.set_cooling_temperature(temp)
        chars = {"CoolingThresholdTemperature": temp}
        if include_active:
            ac.set_active(1)
            chars["Active"] = 1
        ac.handle_hvac_write(chars)

    assert ac.char_cooling_temp.value == 27
    advance(0.299)
    assert controller.commands == []
    advance(0.002)
    assert len(controller.commands) == 1
    assert controller.commands[0].temp_c == 27


def test_fan_and_temperature_share_one_pending_command(debounce_controls) -> None:
    controller, ac, fan, advance = debounce_controls
    ac.set_rotation_speed(20)
    ac.handle_hvac_write({"RotationSpeed": 20})
    advance(0.1)
    ac.set_cooling_temperature(26)
    ac.handle_hvac_write({"CoolingThresholdTemperature": 26})
    advance(0.1)
    fan.set_rotation_speed(80)
    fan.handle_fan_write({"RotationSpeed": 80})

    advance(0.299)
    assert controller.commands == []
    advance(0.002)
    assert len(controller.commands) == 1
    assert controller.commands[0].fan == 4
    assert controller.commands[0].temp_c == 26


def test_separate_adjustments_each_send_after_their_pause(debounce_controls) -> None:
    controller, ac, fan, advance = debounce_controls
    fan.set_rotation_speed(20)
    fan.handle_fan_write({"RotationSpeed": 20})
    advance(0.3)
    ac.set_cooling_temperature(28)
    ac.handle_hvac_write({"CoolingThresholdTemperature": 28})
    advance(0.3)

    assert [(cmd.fan, cmd.temp_c) for cmd in controller.commands] == [(1, 24), (1, 28)]


@pytest.mark.parametrize("surface", ["ac", "fan"])
def test_power_off_immediately_cancels_pending_adjustments(
    debounce_controls, surface
) -> None:
    controller, ac, fan, advance = debounce_controls
    ac.set_cooling_temperature(27)
    ac.handle_hvac_write({"CoolingThresholdTemperature": 27})
    fan.set_rotation_speed(80)
    fan.handle_fan_write({"RotationSpeed": 80})
    control = ac if surface == "ac" else fan
    control.set_active(0)
    if control is ac:
        ac.handle_hvac_write({"Active": 0})
    else:
        fan.handle_fan_write({"Active": 0})

    assert len(controller.commands) == 1
    assert controller.commands[0].power is False
    advance(1)
    assert len(controller.commands) == 1


def test_power_on_with_adjustments_is_immediate(debounce_controls) -> None:
    controller, ac, _, advance = debounce_controls
    ac.set_active(0)
    ac.handle_hvac_write({"Active": 0})
    controller.commands.clear()
    ac.set_active(1)
    ac.set_cooling_temperature(26)
    ac.set_rotation_speed(80)
    ac.handle_hvac_write({
        "Active": 1, "CoolingThresholdTemperature": 26, "RotationSpeed": 80
    })

    assert len(controller.commands) == 1
    assert controller.commands[0].power is True
    assert controller.commands[0].temp_c == 26
    assert controller.commands[0].fan == 4
    advance(1)
    assert len(controller.commands) == 1


@pytest.mark.parametrize("kind", ["mode", "quiet", "swing"])
def test_discrete_controls_send_latest_state_without_delay(
    debounce_controls, kind
) -> None:
    controller, ac, _, advance = debounce_controls
    ac.set_cooling_temperature(27)
    ac.handle_hvac_write({"CoolingThresholdTemperature": 27})
    if kind == "mode":
        control = DaikinModeSwitchAccessory(
            ac.driver, "Dry", ac_accessory=ac, mode=Mode.DRY
        )
        control.set_on(True)
        control.handle_switch_write({"On": True})
    elif kind == "quiet":
        control = DaikinQuietSwitchAccessory(ac.driver, "Quiet", ac_accessory=ac)
        control.set_on(True)
        control.handle_switch_write({"On": True})
    else:
        ac.set_swing(1)
        ac.handle_hvac_write({"SwingMode": 1})

    assert len(controller.commands) == 1
    command = controller.commands[0]
    assert command.temp_c == 27
    assert (command.mode == Mode.DRY) is (kind == "mode")
    assert command.quiet_mode is (kind == "quiet")
    assert command.swing_vertical is (kind == "swing")
    advance(1)
    assert len(controller.commands) == 1


def test_auto_fan_adjustment_preserves_power(debounce_controls) -> None:
    controller, _, fan, advance = debounce_controls
    fan.set_rotation_speed(0)
    fan.handle_fan_write({"RotationSpeed": 0})
    advance(0.3)
    assert len(controller.commands) == 1
    assert controller.commands[0].fan == "auto"
    assert controller.commands[0].power is True


def test_superseded_executor_job_cannot_turn_ac_back_on(
    debounce_controls, monkeypatch
) -> None:
    controller, ac, fan, advance = debounce_controls
    jobs = []

    def add_job(target, *args):
        if is_callback(target):
            target(*args)
        else:
            jobs.append(lambda: target(*args))

    monkeypatch.setattr(ac.driver, "add_job", add_job)
    fan.set_rotation_speed(80)
    fan.handle_fan_write({"RotationSpeed": 80})
    advance(0.3)
    ac.set_active(0)
    ac.handle_hvac_write({"Active": 0})
    assert len(jobs) == 2
    for job in reversed(jobs):
        job()

    assert len(controller.commands) == 1
    assert controller.commands[0].power is False


def test_shutdown_cancels_pending_adjustments(debounce_controls) -> None:
    controller, ac, _, advance = debounce_controls
    ac.set_cooling_temperature(27)
    ac.handle_hvac_write({"CoolingThresholdTemperature": 27})
    ac.driver.loop.run_until_complete(ac.stop())
    advance(1)
    assert controller.commands == []


def test_controller_discovers_once_and_reuses_bound_device(monkeypatch) -> None:
    calls = {
        "select": 0,
        "auth": 0,
        "send": 0,
        "sensors": 0,
    }
    device = object()

    def fake_select_device(**kwargs):
        calls["select"] += 1
        return device

    def fake_authenticate_device(selected_device):
        assert selected_device is device
        calls["auth"] += 1

    def fake_send_ir_packet_to_device(selected_device, packet, **kwargs):
        assert selected_device is device
        calls["send"] += 1

    def fake_read_device_sensors(selected_device):
        assert selected_device is device
        calls["sensors"] += 1
        return Rm4SensorReadings(temperature=25, humidity=60, raw={})

    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.select_device",
        fake_select_device,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.authenticate_device",
        fake_authenticate_device,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.send_ir_packet_to_device",
        fake_send_ir_packet_to_device,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.read_device_sensors",
        fake_read_device_sensors,
    )

    controller = BroadlinkDaikinController(
        BroadlinkTarget(mac="a0:43:b0:b9:f7:f6", sensor_cache_ttl=0),
    )

    controller.connect()
    controller.send(DaikinCommand())
    controller.read_sensors(force=True)
    controller.read_sensors(force=True)

    assert calls == {
        "select": 1,
        "auth": 1,
        "send": 1,
        "sensors": 2,
    }
