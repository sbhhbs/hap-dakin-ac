"""Address overrides for the repeated 24-bit waveform observed on our RF fans.

This is a capture-derived format, not a mapping from manufacturer stickers.
Words are displayed MSB first, with a long mark representing one. Only the
observed B1/C0 envelope and timing ranges are accepted for synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from statistics import median

COMMAND_NIBBLES = {
    "fan_off": 0xC, "fan_high": 0x6, "fan_mid": 0x2,
    "fan_low": 0x8, "light_toggle": 0x5,
}


def normalize_prefix(value: str) -> str:
    value = value.strip()
    if value[:2].lower() == "0x":
        value = value[2:]
    if not re.fullmatch(r"[0-9a-fA-F]{5}", value):
        raise ValueError("RF prefix must be exactly five hex digits, e.g. FFB7A")
    return value.upper()


def _bit(mark: int, space: int, *, terminal: bool = False) -> int:
    if 5 <= mark <= 20 and (terminal or 25 <= space <= 55):
        return 0
    if 25 <= mark <= 55 and (terminal or 5 <= space <= 20):
        return 1
    raise ValueError("unsupported RF data pulse timings")


def _duration(ticks: int) -> bytes:
    return bytes([ticks]) if ticks < 256 else b"\x00" + ticks.to_bytes(2, "big")


@dataclass(frozen=True)
class Fixed24Packet:
    word: int
    pairs: tuple[tuple[int, int], ...]
    header: bytes
    padding: bytes

    @property
    def prefix(self) -> str:
        return f"{self.word >> 4:05X}"

    @property
    def repetitions(self) -> int:
        return len(self.pairs) // 25

    @classmethod
    def decode(cls, packet: bytes) -> Fixed24Packet:
        if len(packet) < 8 or packet[:2] != b"\xb1\xc0":
            raise ValueError("RF overrides require the observed B1/C0 fan format")
        end = int.from_bytes(packet[2:4], "little") + 4
        if end <= 8 or end > len(packet):
            raise ValueError("truncated RF waveform")
        frequency = int.from_bytes(packet[4:8], "little")
        if not 0 < frequency < 1_000_000:
            raise ValueError("invalid B1 RF frequency")
        pulses = []
        offset = 8
        while offset < end:
            ticks = packet[offset]
            offset += 1
            if ticks == 0:
                if offset + 2 > end:
                    raise ValueError("truncated RF pulse duration")
                ticks = int.from_bytes(packet[offset:offset + 2], "big")
                offset += 2
            if ticks == 0:
                raise ValueError("zero RF pulse duration")
            pulses.append(ticks)
        if len(pulses) % 50 or len(pulses) < 100:
            raise ValueError("expected at least two complete 24-bit RF frames")
        pairs = tuple(zip(pulses[::2], pulses[1::2]))
        words = []
        for start in range(0, len(pairs), 25):
            mark, space = pairs[start]
            if not (5 <= mark <= 20 and 250 <= space <= 500):
                raise ValueError("unsupported RF synchronization pulse")
            word = 0
            for index in range(start + 1, start + 25):
                mark, space = pairs[index]
                terminal = index == len(pairs) - 1
                if terminal and not 1000 <= space <= 3000:
                    raise ValueError("expected RF terminal gap")
                word = (word << 1) | _bit(mark, space, terminal=terminal)
            words.append(word)
        if len(set(words)) != 1:
            raise ValueError("RF repeated frames disagree; learn the button again")
        return cls(words[0], pairs, packet[:8], packet[end:])

    def rewrite(self, *, prefix: str | None = None, frequency_mhz: float | None = None) -> bytes:
        target = int(normalize_prefix(prefix), 16) if prefix is not None else self.word >> 4
        pairs = list(self.pairs)
        if target != self.word >> 4:
            # Captured zero/one pulses are asymmetric. Use observed widths for
            # each symbol rather than swapping the mark and space of a bit.
            samples: dict[int, list[tuple[int, int]]] = {0: [], 1: []}
            for index, (mark, space) in enumerate(pairs):
                if index % 25 and index != len(pairs) - 1:
                    samples[_bit(mark, space)].append((mark, space))
            if not all(samples.values()):
                raise ValueError("RF template must contain both zero and one symbols")
            symbols = {
                bit: (round(median(p[0] for p in values)), round(median(p[1] for p in values)))
                for bit, values in samples.items()
            }
            for start in range(0, len(pairs), 25):
                for bit_index in range(20):
                    bit = (target >> (19 - bit_index)) & 1
                    if bit != ((self.word >> (23 - bit_index)) & 1):
                        pairs[start + 1 + bit_index] = symbols[bit]
        header = bytearray(self.header)
        if frequency_mhz is not None:
            if not math.isfinite(frequency_mhz) or not 0 < frequency_mhz < 1000:
                raise ValueError("RF frequency must be a positive MHz value below 1000")
            khz = round(frequency_mhz * 1000)
            if not 0 < khz < 1_000_000:
                raise ValueError("RF frequency must be representable in whole kHz")
            header[4:8] = khz.to_bytes(4, "little")
        waveform = b"".join(_duration(ticks) for pair in pairs for ticks in pair)
        header[2:4] = (len(waveform) + 4).to_bytes(2, "little")
        return bytes(header) + waveform + self.padding
