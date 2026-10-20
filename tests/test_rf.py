import json
import socket
import struct
from unittest.mock import Mock

import pytest
from broadlink.exceptions import NetworkTimeoutError, ReadError, StorageError

from hap_daikin_ac import rf


def rf_packet(marker=1):
    payload = struct.pack("<I", 433860) + bytes([marker, 10, 20, 30])
    return b"\xb1\xc0" + struct.pack("<H", len(payload)) + payload


@pytest.fixture
def profile():
    return rf.RfProfile(
        rm4_host="10.65.160.140", rm4_mac="34:8e:89:e4:cb:96",
        codes={name: rf_packet(i) for i, name in enumerate(rf.COMMANDS, 1)},
    )


def test_profile_round_trip_preserves_opaque_rf_packets(profile, tmp_path):
    path = tmp_path / "private" / "codes.json"
    profile.save(path)
    restored = rf.RfProfile.load(path)
    restored.require_complete()
    assert restored.codes == profile.codes
    assert restored.frequency_mhz == 433.86
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("packet", [b"", b"\x26\x00\x04\x00abcd", b"\xb1\xc0\xff\xffabcd"])
def test_profile_rejects_ir_or_truncated_packets(packet):
    with pytest.raises(ValueError):
        rf.validate_rf_packet(packet)


def test_missing_command_rejected_before_send(profile):
    del profile.codes["light_toggle"]
    with pytest.raises(ValueError, match="light_toggle"):
        profile.require_complete()
    with pytest.raises(ValueError, match="learn light_toggle"):
        profile.packet("light_toggle")


@pytest.mark.parametrize("frequency", [0, -1, float("nan"), float("inf"), 1000])
def test_invalid_frequency_rejected(frequency):
    with pytest.raises(ValueError, match="frequency"):
        rf.RfProfile(frequency_mhz=frequency)


@pytest.fixture
def remote(monkeypatch):
    device = Mock(timeout=3)
    monkeypatch.setattr(rf, "select_device", Mock(return_value=device))
    monkeypatch.setattr(rf, "authenticate_device", Mock())
    return device


def test_controller_reuses_authentication_and_exact_learned_packets(profile, remote):
    controller = rf.RfController(profile)
    controller.send("fan_low")
    controller.send("fan_high")
    assert [call.args[0] for call in remote.send_data.call_args_list] == [
        profile.codes["fan_low"], profile.codes["fan_high"]
    ]
    rf.authenticate_device.assert_called_once_with(remote)
    rf.select_device.assert_called_once_with(
        host=profile.rm4_host, mac=profile.rm4_mac, timeout=3
    )


@pytest.mark.parametrize("fail", [False, True])
def test_light_toggle_has_one_attempt_and_restores_timeout(profile, remote, fail):
    timeouts = []

    def send(packet):
        timeouts.append(remote.timeout)
        if fail:
            raise NetworkTimeoutError()

    remote.send_data.side_effect = send
    controller = rf.RfController(profile)
    if fail:
        with pytest.raises(RuntimeError, match="toggle was not retried"):
            controller.send("light_toggle")
    else:
        controller.send("light_toggle")
    assert timeouts == [0.8]
    assert remote.timeout == 3


def test_dry_run_never_connects(profile, monkeypatch):
    select = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(rf, "select_device", select)
    rf.RfController(profile, dry_run=True).send("light_toggle")
    select.assert_not_called()


def test_learning_waits_for_capture_and_always_exits_learning(profile, remote, monkeypatch):
    monkeypatch.setattr(rf.time, "sleep", lambda seconds: None)
    packet = rf_packet()
    remote.check_data.side_effect = [ReadError(), StorageError(), packet]
    ready = Mock()
    assert rf.RfController(profile).learn(ready=ready) == packet
    remote.find_rf_packet.assert_called_once_with(433.86)
    ready.assert_called_once()
    remote.cancel_sweep_frequency.assert_called_once()


def test_learning_timeout_exits_learning(profile, remote, monkeypatch):
    clock = iter([0, 1, 2])
    monkeypatch.setattr(rf.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError, match="no RF code"):
        rf.RfController(profile).learn(timeout=0.5)
    remote.cancel_sweep_frequency.assert_called_once()


def test_interface_scopes_only_broadlink_sockets_and_restores_namespace(monkeypatch):
    import broadlink.device as device_module

    original = device_module.socket
    conn = Mock(family=socket.AF_INET, type=socket.SOCK_DGRAM)
    factory = Mock(return_value=conn)
    monkeypatch.setattr(rf.sys, "platform", "darwin")
    monkeypatch.setattr(socket, "if_nametoindex", lambda name: 22)
    monkeypatch.setattr(socket, "socket", factory)
    with rf.broadlink_interface("en0"):
        assert socket.socket is factory
        assert device_module.socket.socket(socket.AF_INET, socket.SOCK_DGRAM) is conn
        conn.setsockopt.assert_called_once_with(socket.IPPROTO_IP, 25, 22)
    assert device_module.socket is original


def test_corrupt_profile_reports_configuration_error(tmp_path):
    path = tmp_path / "codes.json"
    path.write_text(json.dumps({"version": 99, "codes": {}}))
    with pytest.raises(ValueError, match="version"):
        rf.RfProfile.load(path)
