from hap_daikin_ac.broadlink_codec import (
    BROADLINK_TERMINATOR,
    broadlink_packet_to_pulses,
    pulses_to_broadlink_packet,
    pulses_to_pronto_hex,
)
from hap_daikin_ac.protocol import (
    BASE_STATE,
    BIT_MARK_US,
    GAP_US,
    HEADER_MARK_US,
    HEADER_SPACE_US,
    ZERO_SPACE_US,
    DaikinCommand,
    has_valid_checksums,
    state_to_pulses,
)


def test_base_state_has_valid_checksums() -> None:
    assert len(BASE_STATE) == 35
    assert has_valid_checksums(BASE_STATE)


def test_command_mutates_expected_daikin_fields() -> None:
    state = DaikinCommand(
        mode="cool",
        power=True,
        temp_c=24,
        fan=5,
        swing_vertical=True,
        swing_horizontal=True,
        quiet_mode=True,
        econo=True,
    ).to_state()

    assert state[21] == 0x39
    assert state[22] == 0x30
    assert state[24] == 0x7F
    assert state[25] & 0x0F == 0x0F
    assert state[29] & 0x20
    assert not state[29] & 0x01
    assert state[32] & 0x04
    assert has_valid_checksums(state)


def test_power_off_keeps_mode_and_clears_power_bit() -> None:
    state = DaikinCommand(mode="heat", power=False, temp_c=20).to_state()

    assert state[21] == 0x48
    assert state[22] == 0x28
    assert has_valid_checksums(state)


def test_daikin_state_to_pulses_shape() -> None:
    pulses = state_to_pulses(BASE_STATE)

    assert len(pulses) == 584
    assert pulses[:10] == [BIT_MARK_US, ZERO_SPACE_US] * 5
    assert pulses[10:14] == [
        BIT_MARK_US,
        ZERO_SPACE_US + GAP_US,
        HEADER_MARK_US,
        HEADER_SPACE_US,
    ]


def test_broadlink_packet_has_length_terminator_and_round_trips() -> None:
    pulses = state_to_pulses(DaikinCommand(temp_c=24, fan="auto").to_state())
    packet = pulses_to_broadlink_packet(pulses)
    payload_len = int.from_bytes(packet[2:4], "little")
    terminator_index = 4 + payload_len

    assert packet.startswith(b"\x26\x00")
    assert packet[terminator_index : terminator_index + 2] == BROADLINK_TERMINATOR
    assert (len(packet) + 4) % 16 == 0
    assert len(broadlink_packet_to_pulses(packet)) == len(pulses)


def test_pronto_output_is_non_repeating_pronto() -> None:
    pulses = state_to_pulses(BASE_STATE)
    pronto = pulses_to_pronto_hex(pulses)
    words = pronto.split()

    assert words[0] == "0000"
    assert words[3] == "0000"
    assert int(words[2], 16) == len(pulses) // 2
