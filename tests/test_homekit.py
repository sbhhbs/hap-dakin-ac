from pyhap.accessory_driver import AccessoryDriver

from hap_daikin_ac.homekit import (
    BroadlinkDaikinController,
    BroadlinkTarget,
    DaikinAcAccessory,
    fan_to_rotation_speed,
    rotation_speed_to_fan,
)
from hap_daikin_ac.protocol import DaikinCommand
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

    monkeypatch.setattr("hap_daikin_ac.homekit.select_device", fake_select_device)
    monkeypatch.setattr(
        "hap_daikin_ac.homekit.authenticate_device",
        fake_authenticate_device,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit.send_ir_packet_to_device",
        fake_send_ir_packet_to_device,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit.read_device_sensors",
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
