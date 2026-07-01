from pyhap.accessory_driver import AccessoryDriver

from hap_daikin_ac.homekit import (
    BroadlinkDaikinController,
    BroadlinkTarget,
    DaikinAcAccessory,
    fan_to_rotation_speed,
    rotation_speed_to_fan,
)
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

    def read_sensors(self, *, force: bool = False) -> Rm4SensorReadings:
        return Rm4SensorReadings(temperature=26.4, humidity=61.2, raw={})


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
