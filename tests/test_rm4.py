from dataclasses import dataclass

import pytest
from broadlink.exceptions import BroadlinkException, NetworkTimeoutError

from hap_daikin_ac import rm4


@dataclass
class FakeRemote:
    host: tuple[str, int]
    mac: bytes

    def send_data(self, packet: bytes) -> None:
        pass


@dataclass
class FailingSensorRemote(FakeRemote):
    error: Exception

    def check_sensors(self) -> dict[str, float]:
        raise self.error


def test_select_device_discovers_by_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    devices = [
        FakeRemote(("192.168.1.20", 80), bytes.fromhex("001122334455")),
        FakeRemote(("192.168.1.21", 80), bytes.fromhex("a043b072bb64")),
    ]

    monkeypatch.setattr(rm4, "discover_devices", lambda **kwargs: devices)

    selected = rm4.select_device(mac="a0:43:b0:72:bb:64")

    assert selected.host[0] == "192.168.1.21"


def test_select_device_accepts_reversed_broadlink_mac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices = [FakeRemote(("192.168.1.21", 80), bytes.fromhex("64bb72b043a0"))]

    monkeypatch.setattr(rm4, "discover_devices", lambda **kwargs: devices)

    selected = rm4.select_device(mac="a0:43:b0:72:bb:64")

    assert selected.host[0] == "192.168.1.21"


def test_select_device_reports_missing_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    devices = [FakeRemote(("192.168.1.20", 80), bytes.fromhex("001122334455"))]

    monkeypatch.setattr(rm4, "discover_devices", lambda **kwargs: devices)

    with pytest.raises(RuntimeError, match="matching MAC a043b072bb64"):
        rm4.select_device(mac="a0:43:b0:72:bb:64")


@pytest.mark.parametrize(
    "sensor_error",
    [NetworkTimeoutError("timed out"), OSError("network unreachable")],
)
def test_read_device_sensors_classifies_connectivity_errors(
    sensor_error: Exception,
) -> None:
    device = FailingSensorRemote(
        ("192.168.1.21", 80), bytes.fromhex("a043b072bb64"), sensor_error
    )

    with pytest.raises(
        rm4.Rm4ConnectivityError, match="Broadlink sensor read failed"
    ) as exc_info:
        rm4.read_device_sensors(device)

    assert exc_info.value.__cause__ is sensor_error


def test_read_device_sensors_keeps_non_connectivity_broadlink_errors_generic() -> None:
    sensor_error = BroadlinkException("unexpected response")
    device = FailingSensorRemote(
        ("192.168.1.21", 80), bytes.fromhex("a043b072bb64"), sensor_error
    )

    with pytest.raises(RuntimeError, match="Broadlink sensor read failed") as exc_info:
        rm4.read_device_sensors(device)

    assert not isinstance(exc_info.value, rm4.Rm4ConnectivityError)
    assert exc_info.value.__cause__ is sensor_error
