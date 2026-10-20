from pathlib import Path

import pytest
from pyhap.accessory_driver import AccessoryDriver

from hap_daikin_ac import rf, rf_cli
from hap_daikin_ac.rf_homekit import RfFanAccessory, RfLightToggleAccessory
from hap_daikin_ac.rf_protocol import Fixed24Packet


@pytest.fixture
def codes(tmp_path):
    path = tmp_path / "codes.json"
    packet = bytes.fromhex("b1c00800c49e060001020304")
    rf.RfProfile(codes={name: packet for name in rf.COMMANDS}).save(path)
    return path


def test_send_dry_run_never_uses_network(codes, monkeypatch, capsys):
    monkeypatch.setattr(rf, "select_device", lambda **kw: pytest.fail("network used"))
    assert rf_cli.main(["send", "fan_high", "--codes", str(codes), "--dry-run"]) == 0
    assert "dry-run: fan_high" in capsys.readouterr().out


def test_missing_profile_fails_before_startup(tmp_path):
    with pytest.raises(SystemExit) as error:
        rf_cli.main(["homekit", "--codes", str(tmp_path / "missing.json"), "--dry-run"])
    assert error.value.code == 2


def test_homekit_has_separate_fan_and_momentary_light(codes, monkeypatch):
    captured = []
    monkeypatch.setattr(AccessoryDriver, "start", lambda driver: captured.append(driver))
    monkeypatch.setattr(rf, "select_device", lambda **kw: pytest.fail("network used"))
    assert rf_cli.main(["homekit", "--codes", str(codes), "--dry-run"]) == 0
    driver = captured[0]
    try:
        assert driver.state.port == 51235
        assert Path(driver.persist_file).name == "homekit.state"
        accessories = list(driver.accessory.accessories.values())
        assert len(accessories) == 2
        assert isinstance(accessories[0], RfFanAccessory)
        assert isinstance(accessories[1], RfLightToggleAccessory)
        assert accessories[1].char_on.value is False
    finally:
        driver.loop.close()


def test_partial_profile_cannot_publish_incomplete_controls(codes):
    profile = rf.RfProfile.load(codes)
    del profile.codes["fan_mid"]
    profile.save(codes)
    with pytest.raises(SystemExit) as error:
        rf_cli.main(["homekit", "--codes", str(codes), "--dry-run"])
    assert error.value.code == 2


def test_env_overrides_generate_selected_address_without_network(fixed24_profile, tmp_path, monkeypatch):
    path = tmp_path / "codes.json"
    fixed24_profile.save(path)
    captured = []
    monkeypatch.setenv("HAP_RF_FAN_PREFIX", "def34")
    monkeypatch.setenv("HAP_RF_FAN_FREQUENCY", "433.78")
    monkeypatch.setattr(rf, "select_device", lambda **kw: pytest.fail("network used"))
    original_send = rf.RfController.send

    def send(controller, command):
        captured.append(controller.profile.packet(command))
        original_send(controller, command)

    monkeypatch.setattr(rf.RfController, "send", send)
    assert rf_cli.main(["send", "fan_high", "--codes", str(path), "--dry-run"]) == 0
    assert Fixed24Packet.decode(captured[0]).word == 0xDEF346
    assert int.from_bytes(captured[0][4:8], "little") == 433780
    assert rf.RfProfile.load(path).codes == fixed24_profile.codes


def test_prefix_instances_have_separate_pairing_state_and_serials(fixed24_profile, tmp_path, monkeypatch):
    path = tmp_path / "codes.json"
    fixed24_profile.save(path)
    captured = []
    monkeypatch.setattr(AccessoryDriver, "start", lambda driver: captured.append(driver))
    monkeypatch.setattr(rf, "select_device", lambda **kw: pytest.fail("network used"))
    monkeypatch.setenv("HAP_RF_FAN_NAME", "Second Fan")
    try:
        for prefix in ("ABC12", "def34"):
            assert rf_cli.main(["homekit", "--codes", str(path), "--dry-run", "--prefix", prefix]) == 0
        assert [Path(d.persist_file).name for d in captured] == ["homekit-abc12.state", "homekit-def34.state"]
        fans = [list(d.accessory.accessories.values())[0] for d in captured]
        serials = [fan.get_service("AccessoryInformation").get_characteristic("SerialNumber").value for fan in fans]
        assert len(set(serials)) == 2
        assert all(fan.display_name == "Second Fan" for fan in fans)
    finally:
        for driver in captured:
            driver.loop.close()


def test_override_unknown_protocol_fails_before_network(codes, monkeypatch):
    monkeypatch.setattr(rf, "select_device", lambda **kw: pytest.fail("network used"))
    with pytest.raises(SystemExit) as error:
        rf_cli.main(["send", "fan_off", "--codes", str(codes), "--prefix", "12345"])
    assert error.value.code == 2
