from pathlib import Path

import pytest
from pyhap.accessory_driver import AccessoryDriver

from hap_daikin_ac import rf, rf_cli
from hap_daikin_ac.rf_homekit import RfFanAccessory, RfLightToggleAccessory


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
