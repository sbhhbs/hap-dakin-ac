# 歌鼎 RF fan and light protocol findings

Recorded on 2026-10-20. These findings come from the two remotes' captured
waveforms. They describe the format supported by this integration, rather than
a manufacturer-confirmed protocol specification.

## Hardware and frequency

The bridge is a Broadlink RM4 Pro at `10.65.160.140`, MAC
`34:8e:89:e4:cb:96`, device type `0x520B`. It authenticated with the existing
`broadlink 0.19.0` dependency. No dependency upgrade was required for this device.

| Remote sticker | Decoded RF address | Learning frequency setting |
| --- | --- | --- |
| `0K24C0109` | `FFB7A` | 433.86 MHz, supplied when learning |
| `0K24C0117` | `FC00E` | 433.78 MHz, selected after frequency sweeps |

The first character of the stickers was initially ambiguous between `O` and
`0`; the labels above use `0K` as discussed with the user. The addresses were
decoded from RF captures, not calculated from the labels.

The second remote's three sweep results were 305.0, 433.76, and 433.78 MHz.
The 305 MHz reading was not reproduced and is treated as an outlier. The first
remote did not receive an equivalent fresh frequency sweep. Packet headers
contain the supplied learning frequency, so they are not an independent
measurement of its carrier. The small frequency difference does not establish
that the fans use separate RF channels. Their captured OFF words have different
address bits, so their difference is not just frequency.

On this Mac, VPN routing interfered with the default route to the RM4. The CLI's
`--interface en0` scopes Broadlink's UDP sockets to Ethernet with macOS
`IP_BOUND_IF`. It does not switch Wi-Fi or change system routes. The HomeKit
advertised address used here is `10.65.5.23`.

## Decoded words and command mapping

Each captured frame contains 24 data bits. We display them MSB first, with a
long mark representing `1`. The first 20 bits stay constant across the first
remote's five buttons and the second remote's two captured buttons. The final
four bits select the button:

| Button | Command nibble | First remote: captured word / complete frames | Second remote: word / evidence |
| --- | --- | --- | --- |
| Fan OFF | `C` | `FFB7AC` / 6 | `FC00EC` / captured, 5 frames |
| Fan HIGH | `6` | `FFB7A6` / 6 | `FC00E6` / captured, 5 frames |
| Fan MID | `2` | `FFB7A2` / 6 | `FC00E2` / inferred |
| Fan LOW | `8` | `FFB7A8` / 5 | `FC00E8` / inferred |
| Light toggle | `5` | `FFB7A5` / 4 | `FC00E5` / inferred |

The observed combination is:

```text
word = (address << 4) | command
```

XOR produces the same word here because the shifted address and four-bit
command occupy different bits. This explains the address/button composition;
it does not explain how the manufacturer assigns an address to a sticker.

The second HIGH word was predicted as `FC00E6` before learning it. An independent
capture then produced exactly `FC00E6` across five identical complete frames.
That provides a cross-check beyond the initial OFF comparison. The generated
and captured words match; their full Broadlink packets need not be byte-identical
because capture timings and repetition counts can differ.

## Broadlink packet and pulse representation

The captured packets use this envelope:

| Byte offset | Observed content |
| --- | --- |
| `0` | RF packet type `B1` |
| `1` | `C0`, preserved unchanged; its meaning was not established |
| `2..3` | Little-endian payload length; payload ends at `4 + length` |
| `4..7` | Little-endian frequency value in kHz: `433860` or `433780` |
| `8..payload end` | Alternating mark/space duration tokens |
| After payload end, if present | Preserved trailing padding |

A nonzero duration byte is the duration in ticks. A zero byte introduces an
extended duration stored in the following two bytes, big endian. The analysis
and synthesis work in captured ticks; no calibrated conversion to microseconds
is required or claimed.

Each frame has 25 mark/space pairs: one synchronization pair followed by 24
data pairs. Observed short durations span 9–15 ticks, long data durations span
31–39 ticks, and synchronization spaces span 348–353 ticks. A data `1` has a
long mark and short space; a data `0` has a short mark and long space.

The final frame's last space is replaced by a 1500-tick terminal gap. The final
data bit is still present in the mark immediately before that gap: short for
`0`, long for `1`. An initial exploratory decoder treated every long space as
a frame boundary and reported only 23 bits in the last frame. Accounting for
the terminal gap recovers a complete final frame, including the final `1` in
the light-toggle command.

## Address override implementation

[rf_protocol.py](../src/hap_daikin_ac/rf_protocol.py) implements decoding and
rewriting. [RfProfile.with_rf_overrides](../src/hap_daikin_ac/rf.py) applies it
to a profile in memory; the original learned code file is not overwritten.

The override path:

1. Requires the observed `B1/C0` envelope and at least two complete repeated
   frames. It checks synchronization, symbol timing ranges, and the terminal gap.
2. Requires every repetition of a packet to decode to the same 24-bit word.
3. Requires all supplied template commands to have the same address and the
   expected command nibbles from the table above.
4. Replaces only differing address bits in every repetition. Replacement zero
   and one symbols use the median mark/space widths observed for each symbol
   in that packet. It does not simply swap mark and space: their learned widths
   are asymmetric.
5. Preserves the command bits, synchronization pairs, terminal gap, repetition
   count, flags, and padding. An optional frequency override updates the header.

Packets without overrides retain their exact learned bytes. For these captures,
applying the original address and frequency also reproduces every packet byte
for byte. Other Broadlink RF formats can still be replayed as opaque learned
packets, but this synthesis path rejects formats it does not recognize.

`HAP_RF_FAN_PREFIX` / `--prefix` accepts the raw five-hex-digit address, optionally
with `0x`; it does not accept or convert a sticker number.
`HAP_RF_FAN_FREQUENCY` / `--frequency` selects the frequency in MHz. Prefix
overrides apply to `send` and `homekit`, not `learn`.

## Running both fans

Keep the first bridge's existing configuration, which uses the complete first
profile and port 51235. Start a second process using that same complete profile
as its timing and command template:

```bash
HAP_RF_FAN_PREFIX=FC00E HAP_RF_FAN_FREQUENCY=433.78 \
HAP_RF_FAN_NAME="Ceiling Fan 2" HAP_RF_FAN_PORT=51236 \
poetry run hap-rf-fan homekit --interface en0 --address 10.65.5.23
```

An explicit prefix selects a separate default pairing file, such as
`homekit-fc00e.state`, and is included in the accessory serial-number identity.
Without a prefix override, the existing `homekit.state` and identity are retained.
Each running bridge needs a different port. A manually supplied `--persist-file`
must also be unique to its bridge.

The second remote's own learned profile currently contains only OFF and HIGH,
so it is incomplete for HomeKit. Use the complete first profile with the second
address override, or learn the remaining three second-remote buttons first.

Check synthesis without connecting to the RM4 or transmitting RF:

```bash
poetry run hap-rf-fan send fan_high --prefix FC00E --frequency 433.78 --dry-run
```

To independently learn an unrecorded button on the second remote:

```bash
poetry run hap-rf-fan learn --interface en0 --frequency 433.78 \
  --codes "$HOME/Library/Application Support/hap-daikin-ac/rf-fan-light/second/codes.json" \
  --button fan_mid
```

The learner prompts before arming, then asks for a brief press and release.
It saves each capture immediately and exits learning mode afterward. Existing
buttons require `--replace` before they can be overwritten.

The HomeKit light control is a momentary toggle button, not a physical on/off
state. Its displayed off state means it is ready for another toggle. The fan
shows the last requested speed; original-remote changes are not reported back.

## Sticker derivation and online research

A fixed XOR of the sticker's numeric suffix does not fit these two samples:

```text
FFB7A XOR FC00E = 03B74    # captured address difference
00109 XOR 00117 = 0001E    # suffix interpreted as hexadecimal
109 XOR 117    = 00018    # suffix interpreted as decimal; result shown in hex
```

If `address = suffix XOR constant`, XORing the two addresses must give the same
result as XORing the two suffixes, because the constant cancels. It does not.
This rules out that simple mapping for those interpretations, not every possible
CRC, hash, lookup, or factory encoding. Two samples are insufficient to establish
a more complex conversion. The sticker may also be a separate production ID.

Searches using 歌鼎, GE DING, GEDING, and the sticker strings found a
[歌鼎 fan remote product listing](https://tao.hooos.com/goods_8neJ8MnTnt9zpWk6yQugq8tbt8-RWRNNzuXavYjRo7Hv.html).
Its product images show three fan speeds and a light-toggle button. No matching
manufacturer manual or sticker-to-address formula was found. The listing was
not used as the source of the decoded protocol or command mapping.

## Evidence and verification boundary

Private captures remain outside Git under:

```text
~/Library/Application Support/hap-daikin-ac/rf-fan-light/
```

| Local file | Purpose |
| --- | --- |
| `codes.json` | Five original first-remote learned packets |
| `second/codes.json` | Independently learned second-remote OFF and HIGH |
| `second-remote-frequency.json` | Three frequency-sweep results |
| `second-remote-code-comparison.json` | Initial exploratory comparison; final-frame decoding was subsequently corrected as described above |
| `second/high-validation.json` | Predicted/captured HIGH words, frame count, and raw capture |
| `address-override-validation.json` | Offline synthesis comparisons, source hashes, and verification status |

The final code check on 2026-10-20 passed **155 tests** with `poetry run pytest -q`.
Tests use synthetic waveforms rather than committing the private captures. They
cover decoding, complete-frame consistency, malformed packet rejection,
rewriting every address bit while preserving command bits, environment options,
and separate HomeKit identities and pairing files. Offline checks against the
actual captures confirmed unchanged original packets and matching second OFF
and HIGH words. The CLI synthesis dry run also completed successfully.

Generated second-remote commands have not been transmitted for physical
verification. An earlier replay of the first remote's learned LOW packet was
acknowledged by the RM4, but the user deferred checking the fan response. The
successful AC IR test established RM4 connectivity, not RF fan operation.
Second-remote MID, LOW, and LIGHT remain predictions until independently captured
or physically verified. No complete two-fan HomeKit runtime verification has
been recorded.
