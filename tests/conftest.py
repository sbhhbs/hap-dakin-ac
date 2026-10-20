import pytest

from hap_daikin_ac.rf import RfProfile
from hap_daikin_ac.rf_protocol import COMMAND_NIBBLES


@pytest.fixture
def fixed24_packet():
    """Synthetic timings; no captured RF payloads are stored in the repo."""
    def build(word, *, repetitions=3, frequency_khz=433860, padding=b""):
        waveform = bytearray()
        for frame in range(repetitions):
            waveform.extend(b"\x0c\x00\x01\x5e")  # sync: 12 / 350
            for bit in range(23, -1, -1):
                one = bool(word & (1 << bit))
                waveform.append(33 if one else 10)
                if frame == repetitions - 1 and bit == 0:
                    waveform.extend(b"\x00\x05\xdc")  # final space: 1500
                else:
                    waveform.append(12 if one else 36)
        return (b"\xb1\xc0" + (len(waveform) + 4).to_bytes(2, "little")
                + frequency_khz.to_bytes(4, "little") + waveform + padding)
    return build


@pytest.fixture
def fixed24_profile(fixed24_packet):
    return RfProfile(codes={
        name: fixed24_packet((0xABC12 << 4) | nibble)
        for name, nibble in COMMAND_NIBBLES.items()
    })
