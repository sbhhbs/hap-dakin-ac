# HAP Daikin AC

Generate Daikin 280-bit IR state bytes, convert them into Daikin IR waveform timings, wrap those timings as Broadlink `2600...` packets, and optionally send them through a Broadlink RM4.

The conversion flow is:

```text
Daikin state bytes -> Daikin IR pulse timings -> Broadlink IR packet -> RM4 send_data()
```

## Setup

```bash
poetry install
```

## Generate A Broadlink Code

```bash
poetry run hap-daikin-ac code --mode cool --power on --temp 24 --fan 5 --swing-v
```

Useful output formats:

```bash
poetry run hap-daikin-ac code --format state
poetry run hap-daikin-ac code --format pronto
poetry run hap-daikin-ac code --format all --spaced
```

## Send Through An RM4

Discover devices:

```bash
poetry run hap-daikin-ac discover
```

Send directly to a known RM4 IP:

```bash
poetry run hap-daikin-ac send --host 192.168.1.50 --mode cool --temp 24 --fan auto
```

Send an already generated Broadlink packet:

```bash
poetry run hap-daikin-ac send --host 192.168.1.50 --packet-hex 2600...
```

## Notes

The default base state is the decoded `cool24` Daikin 280-bit state from the attached notes:

```text
11 DA 27 00 C5 10 00 E7
11 DA 27 00 42 00 10 64
11 DA 27 00 00 39 30 00 A0 00 00 06 60 00 00 C1 80 00 C2
```

The implementation uses the Daikin frame layout documented by `blafois/Daikin-IR-Reverse` and the Daikin 280-bit timings used by IRremoteESP8266: 5 zero header bits, 3 data sections of 8/8/19 bytes, LSB-first bytes, and checksum bytes at indexes 7, 15, and 34.

