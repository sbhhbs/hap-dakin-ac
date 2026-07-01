"""Encode Daikin pulse timings as Broadlink and Pronto IR codes."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

BROADLINK_COMPAT_TICK_US = 8192 / 269
BROADLINK_TERMINATOR = b"\x0d\x05"


def parse_hex_bytes(value: str) -> bytes:
    """Parse hex with optional spaces, colons, dashes, or 0x prefixes."""
    cleaned = re.sub(r"(?i)0x", "", value)
    cleaned = re.sub(r"[^0-9a-fA-F]", "", cleaned)
    if not cleaned:
        raise ValueError("hex value is empty")
    if len(cleaned) % 2:
        raise ValueError("hex value must contain an even number of digits")
    return bytes.fromhex(cleaned)


def format_hex(data: bytes, *, spaced: bool = False) -> str:
    if not spaced:
        return data.hex()
    return " ".join(f"{byte:02x}" for byte in data)


def pulses_to_broadlink_packet(
    pulses: Iterable[int],
    *,
    tick_us: float = BROADLINK_COMPAT_TICK_US,
    include_terminator: bool = True,
    pad: bool = True,
) -> bytes:
    """Convert microsecond pulse timings to a Broadlink IR packet.

    Broadlink learned IR packets are `26 00`, a little-endian payload length,
    timing bytes, then commonly `0d 05` plus encryption block padding.
    """
    if tick_us <= 0:
        raise ValueError("tick_us must be positive")

    payload = bytearray()
    for pulse in pulses:
        if pulse <= 0:
            raise ValueError("pulse durations must be positive microseconds")
        ticks = round(pulse / tick_us)
        if ticks <= 0:
            raise ValueError("pulse duration is too short for Broadlink timing")
        if ticks > 0xFFFF:
            raise ValueError("pulse duration is too long for Broadlink timing")
        if ticks < 0x100:
            payload.append(ticks)
        else:
            payload.append(0)
            payload.extend(ticks.to_bytes(2, "big"))

    packet = bytearray([0x26, 0x00])
    packet.extend(len(payload).to_bytes(2, "little"))
    packet.extend(payload)

    if include_terminator:
        packet.extend(BROADLINK_TERMINATOR)

    if pad:
        remainder = (len(packet) + 4) % 16
        if remainder:
            packet.extend(b"\x00" * (16 - remainder))

    return bytes(packet)


def broadlink_packet_to_pulses(
    packet: bytes,
    *,
    tick_us: float = BROADLINK_COMPAT_TICK_US,
) -> list[int]:
    """Decode the timing payload from a Broadlink IR packet."""
    if len(packet) < 4:
        raise ValueError("Broadlink packet is too short")
    if packet[0] != 0x26:
        raise ValueError("Broadlink IR packet must start with 0x26")
    payload_len = int.from_bytes(packet[2:4], "little")
    end = 4 + payload_len
    if end > len(packet):
        raise ValueError("Broadlink packet length exceeds available data")

    pulses: list[int] = []
    index = 4
    while index < end:
        ticks = packet[index]
        index += 1
        if ticks == 0:
            if index + 2 > end:
                raise ValueError("Broadlink packet has a truncated long timing")
            ticks = int.from_bytes(packet[index : index + 2], "big")
            index += 2
        pulses.append(round(ticks * tick_us))
    return pulses


def pulses_to_pronto_hex(pulses: Sequence[int], *, frequency_hz: int = 38_000) -> str:
    """Convert microsecond pulse timings to a non-repeating Pronto hex code."""
    if frequency_hz <= 0:
        raise ValueError("frequency_hz must be positive")
    if len(pulses) % 2:
        raise ValueError("Pronto requires mark/space pulse pairs")

    frequency_word = round(1_000_000 / (frequency_hz * 0.241246))
    pronto_unit_us = frequency_word * 0.241246
    words = [round(pulse / pronto_unit_us) for pulse in pulses]
    pronto = [0x0000, frequency_word, len(words) // 2, 0x0000, *words]
    return " ".join(f"{word:04X}" for word in pronto)

