"""Command line interface for Daikin IR generation and RM4 sending."""

from __future__ import annotations

import argparse
from typing import Any

from .broadlink_codec import (
    format_hex,
    parse_hex_bytes,
    pulses_to_broadlink_packet,
    pulses_to_pronto_hex,
)
from .protocol import BASE_STATE, DaikinCommand, Mode, state_from_hex, state_to_pulses


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hap-daikin-ac",
        description="Generate Daikin IR codes and send them with a Broadlink RM4.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    code_parser = subparsers.add_parser(
        "code",
        help="generate Daikin state, Pronto, or Broadlink code",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
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
    add_discovery_options(discover_parser)
    discover_parser.set_defaults(func=run_discover)

    return parser


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
    parser.add_argument("--timeout", type=int, default=5, help="network timeout seconds")
    parser.add_argument("--local-ip", help="local interface IP for discovery")
    parser.add_argument("--discover-ip", help="broadcast or device IP for discovery")


def add_broadlink_target_options(parser: argparse.ArgumentParser) -> None:
    add_discovery_options(parser)
    parser.add_argument("--host", help="RM4 IP address; skips broadcast discovery")
    parser.add_argument("--mac", help="optional RM4 MAC address filter")
    parser.add_argument("--repeats", type=int, default=1, help="number of sends")
    parser.add_argument(
        "--repeat-delay",
        type=float,
        default=0.4,
        help="seconds between repeated sends",
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError) as exc:
        parser.exit(2, f"{parser.prog}: error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())

