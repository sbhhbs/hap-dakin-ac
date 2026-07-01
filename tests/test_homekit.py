from pyhap.accessory_driver import AccessoryDriver

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
    assert fan_to_rotation_speed("auto") == 0
    assert fan_to_rotation_speed("quiet") == 0
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


class RecordingController(BroadlinkDaikinController):
    def __init__(self) -> None:
        super().__init__(BroadlinkTarget(dry_run=True))
        self.commands: list[DaikinCommand] = []

    def send(self, command: DaikinCommand) -> None:
        self.commands.append(command)


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
    assert ac_accessory.char_rotation_speed.value == 0
    assert fan_accessory.char_rotation_speed.value == 0

    ac_accessory.set_active(0)
    ac_accessory.handle_hvac_write({"Active": 0})

    assert controller.commands[0].quiet_mode is True
    assert controller.commands[0].fan == "quiet"
    assert controller.commands[0].power is True
    assert controller.commands[-1].quiet_mode is False
    assert controller.commands[-1].power is False
    assert quiet_switch.char_on.value is False


def test_manual_fan_speed_clears_quiet_mode() -> None:
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
    assert controller.commands[-1].fan == 4
    assert controller.commands[-1].quiet_mode is False


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
