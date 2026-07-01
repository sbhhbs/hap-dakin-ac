from dataclasses import dataclass

import pytest

from hap_daikin_ac import rm4


@dataclass
class FakeRemote:
    host: tuple[str, int]
    mac: bytes

    def send_data(self, packet: bytes) -> None:
        pass


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
