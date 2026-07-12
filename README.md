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

Use `--log-level DEBUG` before or after a subcommand for more detailed colored logs:

```bash
poetry run hap-daikin-ac --log-level DEBUG discover
poetry run hap-daikin-ac homekit --log-level DEBUG
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

Or bind to the RM4 by MAC address and let discovery find its DHCP address:

```bash
export HAP_DAIKIN_RM4_MAC_ADDRESS=a0:43:b0:72:bb:64
poetry run hap-daikin-ac send --mode cool --temp 24 --fan auto
```

Send an already generated Broadlink packet:

```bash
poetry run hap-daikin-ac send --host 192.168.1.50 --packet-hex 2600...
```

## Read RM4 Sensors

For RM4 models with temperature/humidity sensors:

```bash
poetry run hap-daikin-ac sensors --host 192.168.1.50
poetry run hap-daikin-ac sensors --host 192.168.1.50 --json
```

## Run As A HomeKit Accessory

The HomeKit server publishes a bridge with a cooling-only AC accessory, a separate Fan accessory, and switch accessories for Dry Mode, Fan Mode, and Quiet Mode. Heat mode is intentionally not advertised because this AC does not support it. Current temperature is read from the RM4 sensor and humidity is exposed as a separate HomeKit humidity sensor.

Dry Mode and Fan Mode are mutually exclusive. If both switches are off, the AC uses Cool mode. Turning the Fan accessory off also turns the AC off and clears the mode switches. Auto fan displays as `64`, Quiet Mode displays as `17`, and changing the fan speed manually turns Quiet Mode off.

```bash
export HAP_DAIKIN_RM4_MAC_ADDRESS=a0:43:b0:72:bb:64
poetry run hap-daikin-ac homekit
```

The server prints a HomeKit QR code and pairing code on startup. Scan the QR code in the Home app, or enter the code manually.

If you previously paired an older standalone version, remove that accessory from the Home app and use a fresh persist file once so HomeKit sees the new bridge shape:

```bash
poetry run hap-daikin-ac homekit --persist-file .hap-daikin-ac-bridge.state
```

HomeKit server settings can be controlled with environment variables:

```bash
export HAP_DAIKIN_HOMEKIT_ADDRESS=192.168.1.10
export HAP_DAIKIN_HOMEKIT_PORT=51234
export HAP_DAIKIN_HOMEKIT_PINCODE=031-45-154
export HAP_DAIKIN_HOMEKIT_NAME="Daikin AC"
export HAP_DAIKIN_MIN_TEMP=10
export HAP_DAIKIN_MAX_TEMP=30
export HAP_DAIKIN_SENSOR_INTERVAL=60
export HAP_DAIKIN_LOGSTASH_URL=http://127.0.0.1:8080
```

`HAP_DAIKIN_MIN_TEMP` and `HAP_DAIKIN_MAX_TEMP` control the setpoint range shown in HomeKit. They must stay inside the Daikin IR protocol range of `10..30` C.

If `HAP_DAIKIN_LOGSTASH_URL` is set, each successful RM4 sensor reading is POSTed as JSON to that Logstash HTTP endpoint. Events include `timestamp`, `temperature_c`, `humidity_percent`, `accessory_name`, RM4 host/MAC/model fields, HomeKit address/port fields, and the container hostname. `HAP_DAIKIN_LOGSTASH_TIMEOUT` controls the POST timeout and defaults to `3` seconds.

For one-shot CLI commands, if `HAP_DAIKIN_RM4_HOST` is unset and `HAP_DAIKIN_RM4_MAC_ADDRESS` or `HAP_DAIKIN_RM4_MAC` is set, the command discovers the RM4 by MAC address and uses the discovered IP. This is the preferred setup for DHCP networks.

For the long-running HomeKit server, the RM4 is discovered and authenticated at startup. When it is configured by MAC address without a fixed host, a sensor connectivity failure starts a single background rediscovery attempt. If DHCP assigned the RM4 a new address, the replacement connection is authenticated and swapped in without restarting HomeKit; failed attempts are logged and retried after the next sensor connectivity failure. An explicit `HAP_DAIKIN_RM4_HOST` remains fixed and disables this automatic MAC rediscovery.

If `HAP_DAIKIN_HOMEKIT_ADDRESS` is unset, HAP-python auto-selects a local address. The default port is `51234`. Pairing state is stored in `.hap-daikin-ac.state` by default.

For testing without sending IR:

```bash
poetry run hap-daikin-ac homekit --dry-run
```

## Run With Docker

The published image is `sbhhbs/hap-dakin-ac`. Use host networking so HomeKit mDNS and Broadlink discovery can work, and mount `/data` to keep HomeKit pairing state across restarts.

```bash
docker run --rm --network host \
  -v hap-daikin-ac:/data \
  -e HAP_DAIKIN_RM4_MAC_ADDRESS=a0:43:b0:72:bb:64 \
  sbhhbs/hap-dakin-ac:latest
```

One-shot CLI commands can use the same image:

```bash
docker run --rm --network host sbhhbs/hap-dakin-ac:latest discover
docker run --rm --network host sbhhbs/hap-dakin-ac:latest sensors --mac a0:43:b0:72:bb:64
```

Or use Docker Compose. The included [docker-compose.yml](docker-compose.yml) saves HomeKit pairing state in the `hap-daikin-ac-state` volume and exposes the supported environment variables with defaults that can be overridden from your shell or a local `.env` file.

```bash
docker compose up -d
docker compose logs -f
```

## Run The ELK Dashboard

The included [docker-compose.elk.yml](docker-compose.elk.yml) runs Elasticsearch, Logstash, Kibana, and a one-shot Kibana setup container. Logstash listens for telemetry on HTTP port `8080`, stores events in `hap-daikin-sensors-*`, and imports a Kibana dashboard for temperature and humidity changes.

```bash
docker compose -f docker-compose.elk.yml up -d
export HAP_DAIKIN_LOGSTASH_URL=http://127.0.0.1:8080
docker compose up -d
```

Open Kibana at [http://localhost:5601](http://localhost:5601), then open the `Daikin RM4 Sensor Dashboard` dashboard. If the HomeKit container is not using host networking and is attached to the ELK Docker network, use `http://logstash:8080` for `HAP_DAIKIN_LOGSTASH_URL` instead.

If you want a single ELK compose file with no external bind-mounted config files, use [docker-compose.elk.standalone.yml](docker-compose.elk.standalone.yml):

```bash
docker compose -f docker-compose.elk.standalone.yml up -d
```

The default Elastic Stack version is `9.4.3`. If you already have an Elasticsearch volume from `8.17.0`, Elasticsearch will not upgrade that data path directly to `9.4.3`; upgrade through `8.19.0` first, or start with a fresh ELK volume if losing the dashboard history is acceptable.

## Notes

The default base state is the decoded `cool24` Daikin 280-bit state from the attached notes:

```text
11 DA 27 00 C5 10 00 E7
11 DA 27 00 42 00 10 64
11 DA 27 00 00 39 30 00 A0 00 00 06 60 00 00 C1 80 00 C2
```

The implementation uses the Daikin frame layout documented by `blafois/Daikin-IR-Reverse` and the Daikin 280-bit timings used by IRremoteESP8266: 5 zero header bits, 3 data sections of 8/8/19 bytes, LSB-first bytes, and checksum bytes at indexes 7, 15, and 34.
