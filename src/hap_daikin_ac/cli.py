"""Command line interface for Daikin IR generation and RM4 sending."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from .broadlink_codec import (
    format_hex,
    parse_hex_bytes,
    pulses_to_broadlink_packet,
    pulses_to_pronto_hex,
)
from .protocol import BASE_STATE, DaikinCommand, Mode, state_from_hex, state_to_pulses

HOMEKIT_ADDRESS_ENV = "HAP_DAIKIN_HOMEKIT_ADDRESS"
HOMEKIT_PORT_ENV = "HAP_DAIKIN_HOMEKIT_PORT"
HOMEKIT_PINCODE_ENV = "HAP_DAIKIN_HOMEKIT_PINCODE"
HOMEKIT_PERSIST_FILE_ENV = "HAP_DAIKIN_HOMEKIT_PERSIST_FILE"
HOMEKIT_NAME_ENV = "HAP_DAIKIN_HOMEKIT_NAME"
LOG_LEVEL_ENV = "HAP_DAIKIN_LOG_LEVEL"
RM4_HOST_ENV = "HAP_DAIKIN_RM4_HOST"
RM4_MAC_ENV = "HAP_DAIKIN_RM4_MAC"
RM4_MAC_ADDRESS_ENV = "HAP_DAIKIN_RM4_MAC_ADDRESS"
RM4_TIMEOUT_ENV = "HAP_DAIKIN_RM4_TIMEOUT"
RM4_LOCAL_IP_ENV = "HAP_DAIKIN_RM4_LOCAL_IP"
RM4_DISCOVER_IP_ENV = "HAP_DAIKIN_RM4_DISCOVER_IP"
RM4_REPEATS_ENV = "HAP_DAIKIN_RM4_REPEATS"
RM4_REPEAT_DELAY_ENV = "HAP_DAIKIN_RM4_REPEAT_DELAY"


def env_value(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def env_int(name: str, default: int) -> int:
    return int(env_value(name, str(default)))


def env_float(name: str, default: float) -> float:
    return float(env_value(name, str(default)))


def env_bool(name: str, default: bool = False) -> bool:
    value = env_value(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes"}


def rm4_mac_from_env() -> str | None:
    return env_value(RM4_MAC_ENV) or env_value(RM4_MAC_ADDRESS_ENV)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hap-daikin-ac",
        description="Generate Daikin IR codes and send them with a Broadlink RM4.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_logging_options(parser, with_defaults=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    code_parser = subparsers.add_parser(
        "code",
        help="generate Daikin state, Pronto, or Broadlink code",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_logging_options(code_parser)
    add_daikin_options(code_parser)
    code_parser.add_argument(
        "--format",
        choices=["broadlink", "pronto", "state", "pulses", "all"],
        default="broadlink",
        help="output format",
    )
    code_parser.add_argument(
        "--spaced",
        action="store_true",
        help="print byte hex with spaces for state and Broadlink output",
    )
    code_parser.set_defaults(func=run_code)

    send_parser = subparsers.add_parser(
        "send",
        help="generate and send a Daikin IR packet through an RM4",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_logging_options(send_parser)
    add_daikin_options(send_parser)
    add_broadlink_target_options(send_parser)
    send_parser.add_argument(
        "--packet-hex",
        help="send an existing Broadlink 2600 hex packet instead of generating one",
    )
    send_parser.add_argument(
        "--print-packet",
        action="store_true",
        help="print the Broadlink packet before sending",
    )
    send_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="generate/select the packet but do not contact the RM4",
    )
    send_parser.set_defaults(func=run_send)

    discover_parser = subparsers.add_parser(
        "discover",
        help="discover Broadlink devices on the local network",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_logging_options(discover_parser)
    add_discovery_options(discover_parser)
    discover_parser.set_defaults(func=run_discover)

    sensors_parser = subparsers.add_parser(
        "sensors",
        help="read temperature and humidity from the Broadlink RM4 sensors",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_logging_options(sensors_parser)
    add_broadlink_target_options(sensors_parser, include_send_options=False)
    sensors_parser.add_argument(
        "--json",
        action="store_true",
        help="print sensor readings as JSON",
    )
    sensors_parser.set_defaults(func=run_sensors)

    homekit_parser = subparsers.add_parser(
        "homekit",
        help="run a HomeKit AC accessory backed by the Broadlink RM4",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    add_logging_options(homekit_parser)
    add_homekit_options(homekit_parser)
    add_broadlink_target_options(homekit_parser)
    homekit_parser.set_defaults(func=run_homekit)

    return parser


def add_logging_options(
    parser: argparse.ArgumentParser,
    *,
    with_defaults: bool = False,
) -> None:
    default_level = env_value(LOG_LEVEL_ENV, "INFO") if with_defaults else argparse.SUPPRESS
    default_no_color = (
        os.getenv("NO_COLOR") is not None or env_bool("HAP_DAIKIN_NO_COLOR")
        if with_defaults
        else argparse.SUPPRESS
    )
    parser.add_argument(
        "--log-level",
        default=default_level,
        help=f"log level; env {LOG_LEVEL_ENV}",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=default_no_color,
        help="disable colored logs; env NO_COLOR or HAP_DAIKIN_NO_COLOR=1",
    )


def add_daikin_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-state",
        default=BASE_STATE.hex(),
        help="35-byte Daikin 280-bit base state hex",
    )
    parser.add_argument("--power", choices=["on", "off"], default="on")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in Mode],
        default=Mode.COOL.value,
    )
    parser.add_argument("--temp", type=int, default=24, help="target temperature in C")
    parser.add_argument(
        "--fan",
        default="auto",
        help="fan speed: 1..5, auto, or quiet",
    )
    parser.add_argument(
        "--swing-v",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="enable vertical swing",
    )
    parser.add_argument(
        "--swing-h",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="enable horizontal swing",
    )
    parser.add_argument(
        "--quiet-mode",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="toggle the Daikin quiet feature bit",
    )
    parser.add_argument(
        "--powerful",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="toggle the Daikin powerful feature bit",
    )
    parser.add_argument(
        "--econo",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="toggle the Daikin econo feature bit",
    )


def add_discovery_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout",
        type=int,
        default=env_int(RM4_TIMEOUT_ENV, 5),
        help=f"network timeout seconds; env {RM4_TIMEOUT_ENV}",
    )
    parser.add_argument(
        "--local-ip",
        default=env_value(RM4_LOCAL_IP_ENV),
        help=f"local interface IP for discovery; env {RM4_LOCAL_IP_ENV}",
    )
    parser.add_argument(
        "--discover-ip",
        default=env_value(RM4_DISCOVER_IP_ENV),
        help=f"broadcast or device IP for discovery; env {RM4_DISCOVER_IP_ENV}",
    )


def add_broadlink_target_options(
    parser: argparse.ArgumentParser,
    *,
    include_send_options: bool = True,
) -> None:
    add_discovery_options(parser)
    parser.add_argument(
        "--host",
        default=env_value(RM4_HOST_ENV),
        help=f"RM4 IP address; skips broadcast discovery; env {RM4_HOST_ENV}",
    )
    parser.add_argument(
        "--mac",
        default=rm4_mac_from_env(),
        help=(
            "optional RM4 MAC address filter; when --host is absent, discovery "
            f"selects the RM4 by MAC; env {RM4_MAC_ENV} or {RM4_MAC_ADDRESS_ENV}"
        ),
    )
    if not include_send_options:
        return

    parser.add_argument(
        "--repeats",
        type=int,
        default=env_int(RM4_REPEATS_ENV, 1),
        help=f"number of sends; env {RM4_REPEATS_ENV}",
    )
    parser.add_argument(
        "--repeat-delay",
        type=float,
        default=env_float(RM4_REPEAT_DELAY_ENV, 0.4),
        help=f"seconds between repeated sends; env {RM4_REPEAT_DELAY_ENV}",
    )


def add_homekit_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--address",
        default=env_value(HOMEKIT_ADDRESS_ENV),
        help=(
            "HomeKit server address; defaults to HAP-python auto-detection; "
            f"env {HOMEKIT_ADDRESS_ENV}"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=env_int(HOMEKIT_PORT_ENV, 51234),
        help=f"HomeKit server port; env {HOMEKIT_PORT_ENV}",
    )
    parser.add_argument(
        "--pincode",
        default=env_value(HOMEKIT_PINCODE_ENV, "031-45-154"),
        help=f"HomeKit pairing code; env {HOMEKIT_PINCODE_ENV}",
    )
    parser.add_argument(
        "--persist-file",
        default=env_value(HOMEKIT_PERSIST_FILE_ENV, ".hap-daikin-ac.state"),
        help=f"HomeKit pairing state file; env {HOMEKIT_PERSIST_FILE_ENV}",
    )
    parser.add_argument(
        "--name",
        default=env_value(HOMEKIT_NAME_ENV, "Daikin AC"),
        help=f"HomeKit accessory name; env {HOMEKIT_NAME_ENV}",
    )
    parser.add_argument(
        "--initial-temp",
        type=int,
        default=env_int("HAP_DAIKIN_INITIAL_TEMP", 24),
        help="initial cooling setpoint in C; env HAP_DAIKIN_INITIAL_TEMP",
    )
    parser.add_argument(
        "--initial-fan",
        default=env_value("HAP_DAIKIN_INITIAL_FAN", "auto"),
        help="initial fan speed: auto or 1..5; env HAP_DAIKIN_INITIAL_FAN",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=env_bool("HAP_DAIKIN_DRY_RUN"),
        help="log generated Broadlink packets instead of sending them",
    )
    parser.add_argument(
        "--sensor-interval",
        type=float,
        default=env_float("HAP_DAIKIN_SENSOR_INTERVAL", 60),
        help=(
            "seconds between RM4 sensor refreshes in HomeKit; "
            "env HAP_DAIKIN_SENSOR_INTERVAL; use 0 to disable polling"
        ),
    )


def command_from_args(args: argparse.Namespace) -> DaikinCommand:
    return DaikinCommand(
        power=args.power == "on",
        mode=args.mode,
        temp_c=args.temp,
        fan=args.fan,
        swing_vertical=args.swing_v,
        swing_horizontal=args.swing_h,
        quiet_mode=args.quiet_mode,
        powerful=args.powerful,
        econo=args.econo,
        base_state=state_from_hex(args.base_state),
    )


def generate_outputs(args: argparse.Namespace) -> dict[str, Any]:
    state = command_from_args(args).to_state()
    pulses = state_to_pulses(state)
    packet = pulses_to_broadlink_packet(pulses)
    return {
        "state": state,
        "pulses": pulses,
        "broadlink": packet,
        "pronto": pulses_to_pronto_hex(pulses),
    }


def run_code(args: argparse.Namespace) -> int:
    outputs = generate_outputs(args)
    output_format = args.format

    if output_format == "state":
        print(format_hex(outputs["state"], spaced=args.spaced))
    elif output_format == "broadlink":
        print(format_hex(outputs["broadlink"], spaced=args.spaced))
    elif output_format == "pronto":
        print(outputs["pronto"])
    elif output_format == "pulses":
        print(",".join(str(pulse) for pulse in outputs["pulses"]))
    elif output_format == "all":
        print(f"state: {format_hex(outputs['state'], spaced=args.spaced)}")
        print(f"broadlink: {format_hex(outputs['broadlink'], spaced=args.spaced)}")
        print(f"pronto: {outputs['pronto']}")
    return 0


def run_send(args: argparse.Namespace) -> int:
    if args.packet_hex:
        packet = parse_hex_bytes(args.packet_hex)
    else:
        packet = generate_outputs(args)["broadlink"]

    if args.print_packet or args.dry_run:
        print(format_hex(packet))

    if args.dry_run:
        return 0

    from .rm4 import device_summary, send_ir_packet

    device = send_ir_packet(
        packet,
        host=args.host,
        mac=args.mac,
        timeout=args.timeout,
        repeats=args.repeats,
        repeat_delay=args.repeat_delay,
        local_ip_address=args.local_ip,
        discover_ip_address=args.discover_ip,
    )
    print(f"sent via {device_summary(device)}")
    return 0


def run_discover(args: argparse.Namespace) -> int:
    from .rm4 import device_summary, discover_devices

    devices = discover_devices(
        timeout=args.timeout,
        local_ip_address=args.local_ip,
        discover_ip_address=args.discover_ip,
    )
    if not devices:
        print("no devices found")
        return 1
    for device in devices:
        marker = " rm" if hasattr(device, "send_data") else ""
        print(f"{device_summary(device)}{marker}")
    return 0


def run_sensors(args: argparse.Namespace) -> int:
    from .rm4 import read_sensors

    readings = read_sensors(
        host=args.host,
        mac=args.mac,
        timeout=args.timeout,
        local_ip_address=args.local_ip,
        discover_ip_address=args.discover_ip,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "temperature": readings.temperature,
                    "humidity": readings.humidity,
                    "raw": readings.raw,
                },
                sort_keys=True,
            )
        )
        return 0

    if readings.temperature is not None:
        print(f"temperature: {readings.temperature:.2f} C")
    else:
        print("temperature: unavailable")

    if readings.humidity is not None:
        print(f"humidity: {readings.humidity:.2f} %")
    else:
        print("humidity: unavailable")
    return 0


def run_homekit(args: argparse.Namespace) -> int:
    from .pyhap_compat import install_child_watcher_compat

    install_child_watcher_compat()

    from pyhap.accessory import Bridge
    from pyhap.accessory_driver import AccessoryDriver

    from .homekit import (
        BroadlinkDaikinController,
        BroadlinkTarget,
        DaikinAcAccessory,
        DaikinFanAccessory,
        DaikinModeSwitchAccessory,
        DaikinQuietSwitchAccessory,
    )

    target = BroadlinkTarget(
        host=args.host,
        mac=args.mac,
        timeout=args.timeout,
        repeats=args.repeats,
        repeat_delay=args.repeat_delay,
        local_ip_address=args.local_ip,
        discover_ip_address=args.discover_ip,
        dry_run=args.dry_run,
        sensor_cache_ttl=args.sensor_interval,
    )
    controller = BroadlinkDaikinController(target)
    controller.connect()
    driver = AccessoryDriver(
        address=args.address,
        port=args.port,
        persist_file=args.persist_file,
        pincode=args.pincode.encode("ascii"),
    )
    bridge = Bridge(driver, f"{args.name} Bridge")
    ac_accessory = DaikinAcAccessory(
        driver,
        args.name,
        controller=controller,
        initial_temp=args.initial_temp,
        initial_fan=args.initial_fan,
        sensor_poll_interval=args.sensor_interval,
    )
    fan_accessory = DaikinFanAccessory(
        driver,
        "Fan Speed",
        ac_accessory=ac_accessory,
    )
    dry_switch_accessory = DaikinModeSwitchAccessory(
        driver,
        "Dry",
        ac_accessory=ac_accessory,
        mode="dry",
    )
    fan_mode_switch_accessory = DaikinModeSwitchAccessory(
        driver,
        "Fan",
        ac_accessory=ac_accessory,
        mode="fan",
    )
    quiet_switch_accessory = DaikinQuietSwitchAccessory(
        driver,
        "Quiet",
        ac_accessory=ac_accessory,
    )
    ac_accessory.register_fan_accessory(fan_accessory)
    ac_accessory.register_mode_switch_accessory(dry_switch_accessory)
    ac_accessory.register_mode_switch_accessory(fan_mode_switch_accessory)
    ac_accessory.register_quiet_switch_accessory(quiet_switch_accessory)
    bridge.add_accessory(ac_accessory)
    bridge.add_accessory(fan_accessory)
    bridge.add_accessory(dry_switch_accessory)
    bridge.add_accessory(fan_mode_switch_accessory)
    bridge.add_accessory(quiet_switch_accessory)
    driver.add_accessory(accessory=bridge)
    driver.start()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from .logging_config import configure_logging

    configure_logging(args.log_level, color=not args.no_color)
    try:
        return args.func(args)
    except (RuntimeError, ValueError) as exc:
        parser.exit(2, f"{parser.prog}: error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
