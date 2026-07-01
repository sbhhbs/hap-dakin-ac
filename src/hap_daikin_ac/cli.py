"""Command line interface for Daikin IR generation and RM4 sending."""

from __future__ import annotations

import argparse
import json
from typing import Any

from .broadlink_codec import (
    format_hex,
    parse_hex_bytes,
    pulses_to_broadlink_packet,
    pulses_to_pronto_hex,
)
from .cli_options import (
    add_broadlink_target_options,
    add_daikin_options,
    add_discovery_options,
    add_homekit_options,
    add_logging_options,
)
from .protocol import DaikinCommand, state_from_hex, state_to_pulses


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
        min_temp=args.min_temp,
        max_temp=args.max_temp,
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
