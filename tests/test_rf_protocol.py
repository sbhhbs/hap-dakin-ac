import pytest

from hap_daikin_ac.rf_protocol import COMMAND_NIBBLES, Fixed24Packet, normalize_prefix


@pytest.mark.parametrize("nibble", COMMAND_NIBBLES.values())
def test_decode_includes_last_bit_before_terminal_gap(fixed24_packet, nibble):
    packet = fixed24_packet(0xABC120 | nibble, padding=b"\x00\x00")
    decoded = Fixed24Packet.decode(packet)
    assert decoded.word == 0xABC120 | nibble
    assert decoded.prefix == "ABC12"
    assert decoded.repetitions == 3
    assert decoded.rewrite(prefix="ABC12", frequency_mhz=433.86) == packet


@pytest.mark.parametrize("prefix", ["00000", "FFFFF", "DEF34"])
@pytest.mark.parametrize("nibble", COMMAND_NIBBLES.values())
def test_rewrite_every_repetition_preserves_command_and_envelope(fixed24_packet, prefix, nibble):
    packet = fixed24_packet(0xABC120 | nibble, padding=b"\x00\x00")
    rewritten = Fixed24Packet.decode(packet).rewrite(prefix=prefix, frequency_mhz=433.78)
    assert rewritten == fixed24_packet(
        (int(prefix, 16) << 4) | nibble, frequency_khz=433780, padding=b"\x00\x00"
    )


def test_mixed_repetitions_are_rejected(fixed24_packet):
    packet = bytearray(fixed24_packet(0xABC12C))
    assert packet[12:14] == b"\x21\x0c"
    packet[12:14] = b"\x0a\x24"  # change one frame's leading bit
    with pytest.raises(ValueError, match="frames disagree"):
        Fixed24Packet.decode(packet)


@pytest.mark.parametrize("damage", ["format", "truncated", "duration", "noise", "gap", "one_frame"])
def test_unknown_or_corrupted_waveforms_rejected(fixed24_packet, damage):
    packet = bytearray(fixed24_packet(0xABC12C, repetitions=1 if damage == "one_frame" else 3))
    if damage == "format":
        packet[0] = 0xB2
    elif damage == "truncated":
        packet.pop()
    elif damage == "duration":
        packet.pop()
        packet[2:4] = (len(packet) - 4).to_bytes(2, "little")
    elif damage == "noise":
        packet[12] = 23
    elif damage == "gap":
        packet[-2:] = b"\x00\x64"
    with pytest.raises(ValueError):
        Fixed24Packet.decode(packet)


@pytest.mark.parametrize("value", ["ABC12", "abc12", "0xabc12", "0XABC12"])
def test_prefix_is_canonical(value):
    assert normalize_prefix(value) == "ABC12"


@pytest.mark.parametrize("value", ["0109", "0K24C0109", "100000", "-1234", "xyz12", "0x0XABC12", ""])
def test_prefix_requires_raw_twenty_bit_address(value):
    with pytest.raises(ValueError, match="five hex digits"):
        normalize_prefix(value)


def test_profile_override_leaves_original_capture_intact(fixed24_profile, tmp_path):
    path = tmp_path / "codes.json"
    fixed24_profile.save(path)
    original_file = path.read_bytes()
    original_codes = fixed24_profile.codes.copy()
    rewritten = fixed24_profile.with_rf_overrides(prefix="def34", frequency_mhz=433.78)
    for name, packet in rewritten.codes.items():
        assert Fixed24Packet.decode(packet).word == (0xDEF34 << 4) | COMMAND_NIBBLES[name]
        assert int.from_bytes(packet[4:8], "little") == 433780
    assert rewritten.frequency_mhz == 433.78
    assert fixed24_profile.codes == original_codes
    assert path.read_bytes() == original_file
    assert fixed24_profile.with_rf_overrides() is fixed24_profile


@pytest.mark.parametrize("problem", ["mixed_address", "wrong_command"])
def test_override_rejects_templates_from_another_remote_format(fixed24_profile, fixed24_packet, problem):
    word = 0xDEF34C if problem == "mixed_address" else 0xABC12F
    fixed24_profile.codes["fan_off"] = fixed24_packet(word)
    with pytest.raises(ValueError, match="same fan address|command format"):
        fixed24_profile.with_rf_overrides(prefix="12345")


def test_frequency_only_override_preserves_all_symbols(fixed24_profile):
    rewritten = fixed24_profile.with_rf_overrides(frequency_mhz=433.78)
    for name, original in fixed24_profile.codes.items():
        assert rewritten.codes[name][:4] == original[:4]
        assert rewritten.codes[name][8:] == original[8:]


@pytest.mark.parametrize("frequency", [0, -10, float("nan"), float("inf"), 1000])
def test_bad_override_frequency_fails_before_synthesis(fixed24_profile, frequency):
    with pytest.raises(ValueError, match="frequency"):
        fixed24_profile.with_rf_overrides(frequency_mhz=frequency)
