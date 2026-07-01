"""Daikin 280-bit state generation and pulse encoding."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .broadlink_codec import parse_hex_bytes

BASE_STATE = bytes.fromhex(
    "11da2700c51000e7"
    "11da270042001064"
    "11da270000393000a0000006600000c18000c2"
)

SECTIONS = (8, 8, 19)
STATE_LENGTH = sum(SECTIONS)

HEADER_MARK_US = 3650
HEADER_SPACE_US = 1623
BIT_MARK_US = 428
ZERO_SPACE_US = 428
ONE_SPACE_US = 1280
GAP_US = 29_000
DAIKIN_HEADER_ZERO_BITS = 5

MIN_TEMP_C = 10
MAX_TEMP_C = 30

POWER_MODE_INDEX = 21
TEMP_INDEX = 22
FAN_SWING_V_INDEX = 24
SWING_H_INDEX = 25
POWERFUL_QUIET_INDEX = 29
ECONO_INDEX = 32


class Mode(StrEnum):
    AUTO = "auto"
    DRY = "dry"
    COOL = "cool"
    HEAT = "heat"
    FAN = "fan"


MODE_CODES = {
    Mode.AUTO: 0x0,
    Mode.DRY: 0x2,
    Mode.COOL: 0x3,
    Mode.HEAT: 0x4,
    Mode.FAN: 0x6,
}


@dataclass(frozen=True)
class DaikinCommand:
    power: bool = True
    mode: Mode | str = Mode.COOL
    temp_c: int = 24
    fan: int | str = "auto"
    swing_vertical: bool = False
    swing_horizontal: bool = False
    quiet_mode: bool = False
    powerful: bool = False
    econo: bool = False
    base_state: bytes = BASE_STATE

    def to_state(self) -> bytes:
        """Return a checksum-corrected 35-byte Daikin 280-bit state."""
        state = bytearray(self.base_state)
        require_state_length(state)

        mode = normalize_mode(self.mode)
        validate_temp(self.temp_c)

        state[POWER_MODE_INDEX] = (MODE_CODES[mode] << 4) | 0x08
        if self.power:
            state[POWER_MODE_INDEX] |= 0x01

        state[TEMP_INDEX] = self.temp_c * 2
        set_fan(state, self.fan)
        set_vertical_swing(state, self.swing_vertical)
        set_horizontal_swing(state, self.swing_horizontal)

        if self.quiet_mode and self.powerful:
            raise ValueError("quiet_mode and powerful cannot both be enabled")
        set_quiet_mode(state, self.quiet_mode)
        set_powerful(state, self.powerful)
        set_econo(state, self.econo)

        fix_checksums(state)
        return bytes(state)


def normalize_mode(mode: Mode | str) -> Mode:
    if isinstance(mode, Mode):
        return mode
    try:
        return Mode(str(mode).lower())
    except ValueError as exc:
        choices = ", ".join(item.value for item in Mode)
        raise ValueError(f"mode must be one of: {choices}") from exc


def validate_temp(temp_c: int) -> None:
    if not MIN_TEMP_C <= temp_c <= MAX_TEMP_C:
        raise ValueError(f"temp_c must be between {MIN_TEMP_C} and {MAX_TEMP_C}")


def require_state_length(state: bytes | bytearray) -> None:
    if len(state) != STATE_LENGTH:
        raise ValueError(f"Daikin 280-bit state must be {STATE_LENGTH} bytes")


def state_from_hex(value: str) -> bytes:
    state = parse_hex_bytes(value)
    require_state_length(state)
    return state


def fix_checksums(state: bytearray) -> bytearray:
    """Set each section checksum to the low byte of its section sum."""
    require_state_length(state)
    offset = 0
    for section_len in SECTIONS:
        checksum_index = offset + section_len - 1
        state[checksum_index] = sum(state[offset:checksum_index]) & 0xFF
        offset += section_len
    return state


def has_valid_checksums(state: bytes | bytearray) -> bool:
    require_state_length(state)
    offset = 0
    for section_len in SECTIONS:
        checksum_index = offset + section_len - 1
        if state[checksum_index] != sum(state[offset:checksum_index]) & 0xFF:
            return False
        offset += section_len
    return True


def fan_to_native(fan: int | str) -> int:
    if isinstance(fan, str):
        normalized = fan.strip().lower()
        if normalized == "auto":
            return 0xA
        if normalized in {"quiet", "silent"}:
            return 0xB
        if normalized.isdecimal():
            fan = int(normalized)
        else:
            raise ValueError("fan must be 1..5, auto, or quiet")

    fan_int = int(fan)
    if not 1 <= fan_int <= 5:
        raise ValueError("fan must be 1..5, auto, or quiet")
    return fan_int + 2


def set_fan(state: bytearray, fan: int | str) -> None:
    native = fan_to_native(fan)
    state[FAN_SWING_V_INDEX] = (state[FAN_SWING_V_INDEX] & 0x0F) | (native << 4)


def set_vertical_swing(state: bytearray, enabled: bool) -> None:
    state[FAN_SWING_V_INDEX] = (state[FAN_SWING_V_INDEX] & 0xF0) | (
        0x0F if enabled else 0x00
    )


def set_horizontal_swing(state: bytearray, enabled: bool) -> None:
    state[SWING_H_INDEX] = (state[SWING_H_INDEX] & 0xF0) | (
        0x0F if enabled else 0x00
    )


def set_quiet_mode(state: bytearray, enabled: bool) -> None:
    if enabled:
        state[POWERFUL_QUIET_INDEX] |= 0x20
        state[POWERFUL_QUIET_INDEX] &= ~0x01
    else:
        state[POWERFUL_QUIET_INDEX] &= ~0x20


def set_powerful(state: bytearray, enabled: bool) -> None:
    if enabled:
        state[POWERFUL_QUIET_INDEX] |= 0x01
        state[POWERFUL_QUIET_INDEX] &= ~0x20
    else:
        state[POWERFUL_QUIET_INDEX] &= ~0x01


def set_econo(state: bytearray, enabled: bool) -> None:
    if enabled:
        state[ECONO_INDEX] |= 0x04
    else:
        state[ECONO_INDEX] &= ~0x04


def state_to_pulses(state: bytes | bytearray) -> list[int]:
    """Convert a Daikin 280-bit state into mark/space pulse timings."""
    require_state_length(state)
    pulses: list[int] = []

    for _ in range(DAIKIN_HEADER_ZERO_BITS):
        pulses.extend([BIT_MARK_US, ZERO_SPACE_US])
    pulses.extend([BIT_MARK_US, ZERO_SPACE_US + GAP_US])

    offset = 0
    for section_len in SECTIONS:
        pulses.extend([HEADER_MARK_US, HEADER_SPACE_US])
        section = state[offset : offset + section_len]
        for byte in section:
            for bit in range(8):
                pulses.extend(
                    [
                        BIT_MARK_US,
                        ONE_SPACE_US if byte & (1 << bit) else ZERO_SPACE_US,
                    ]
                )
        pulses.extend([BIT_MARK_US, ZERO_SPACE_US + GAP_US])
        offset += section_len

    return pulses

