"""Dedicated CLI and HomeKit bridge for an RF fan with a toggle-only light."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
from pathlib import Path

from .rf import COMMANDS, RfController, RfProfile, broadlink_interface, default_profile_path
from .rf_protocol import normalize_prefix


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("learn", "send", "homekit"):
        command = sub.add_parser(action)
        command.add_argument("--codes", type=Path, default=Path(os.getenv("HAP_RF_FAN_CODES", str(default_profile_path()))))
        command.add_argument("--host", default=os.getenv("HAP_RF_FAN_HOST"))
        command.add_argument("--mac", default=os.getenv("HAP_RF_FAN_MAC"))
        command.add_argument("--interface", default=os.getenv("HAP_RF_FAN_INTERFACE"), help="macOS network interface, e.g. en0")
        command.add_argument("--timeout", type=float, default=3)
        command.add_argument("--frequency", type=float, default=os.getenv("HAP_RF_FAN_FREQUENCY"),
                             help="RF MHz; overrides the learned carrier for send/homekit")
        if action != "learn":
            command.add_argument("--dry-run", action="store_true")
            command.add_argument("--prefix", type=normalize_prefix, default=os.getenv("HAP_RF_FAN_PREFIX"),
                                 help="five-hex-digit RF address, not the printed sticker number")
        if action == "send":
            command.add_argument("command", choices=COMMANDS)
        elif action == "learn":
            command.add_argument("--button", choices=COMMANDS, help="omit to learn all five commands")
            command.add_argument("--learn-timeout", type=float, default=60)
            command.add_argument("--replace", action="store_true")
        else:
            command.add_argument("--address", default=os.getenv("HAP_RF_FAN_ADDRESS"))
            command.add_argument("--port", type=int, default=int(os.getenv("HAP_RF_FAN_PORT", "51235")))
            command.add_argument("--name", default=os.getenv("HAP_RF_FAN_NAME"))
            command.add_argument("--light-name", default="Light Toggle")
            command.add_argument("--persist-file", type=Path, default=None)
            command.add_argument("--pincode", help="optional HomeKit PIN in XXX-XX-XXX form")
    return parser


def run_learning(args, profile: RfProfile) -> int:
    if args.frequency is not None:
        profile.frequency_mhz = args.frequency
    if args.host:
        profile.rm4_host = args.host
    if args.mac:
        profile.rm4_mac = args.mac
    buttons = (args.button,) if args.button else COMMANDS
    if not args.replace and any(button in profile.codes for button in buttons):
        raise ValueError("a selected button is already learned; use --replace to overwrite")
    controller = RfController(profile, timeout=args.timeout)
    try:
        controller.connect()
        for button in buttons:
            input(f"Have {button.replace('_', ' ').upper()} ready; press Enter to arm learning: ")
            packet = controller.learn(
                timeout=args.learn_timeout,
                ready=lambda: print("Listening now: briefly press and release that button.", flush=True),
            )
            profile.codes[button] = packet
            profile.save(args.codes)
            print(f"Saved {button}: {len(packet)} bytes to {args.codes}", flush=True)
    finally:
        controller.close()
    return 0


def run_homekit(args, profile: RfProfile, controller: RfController) -> int:
    from .pyhap_compat import install_child_watcher_compat

    install_child_watcher_compat()
    from pyhap.accessory import Bridge
    from .rf_homekit import RfAccessoryDriver, RfFanAccessory, RfLightToggleAccessory

    profile.require_complete()
    name = args.name or profile.name
    state_name = f"homekit-{args.prefix.lower()}.state" if args.prefix else "homekit.state"
    persist = args.persist_file or args.codes.with_name(state_name)
    persist.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = f"{profile.name}|{controller.mac}"
    if args.prefix:
        identity += f"|{args.prefix}"
    serial = hashlib.sha256(identity.encode()).hexdigest()[:12]
    controller.connect()
    driver = RfAccessoryDriver(
        address=args.address, port=args.port, persist_file=str(persist),
        pincode=args.pincode.encode("ascii") if args.pincode else None,
    )
    bridge = Bridge(driver, f"{name} Bridge")
    bridge.add_accessory(RfFanAccessory(driver, name, controller=controller, serial=f"{serial}-fan"))
    bridge.add_accessory(RfLightToggleAccessory(driver, args.light_name, controller=controller, serial=f"{serial}-light"))
    driver.add_accessory(bridge)
    driver.start()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.codes = args.codes.expanduser()
    if getattr(args, "persist_file", None):
        args.persist_file = args.persist_file.expanduser()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.timeout <= 0:
            raise ValueError("timeout must be positive")
        profile = RfProfile.load(args.codes) if args.codes.exists() else RfProfile()
        if args.action != "learn" and not args.codes.exists():
            raise ValueError(f"learn RF commands first: no profile at {args.codes}")
        with broadlink_interface(args.interface):
            if args.action == "learn":
                return run_learning(args, profile)
            profile = profile.with_rf_overrides(prefix=args.prefix, frequency_mhz=args.frequency)
            controller = RfController(
                profile, host=args.host, mac=args.mac, timeout=args.timeout, dry_run=args.dry_run
            )
            try:
                if args.action == "send":
                    controller.send(args.command)
                    print(f"{'dry-run' if args.dry_run else 'sent'}: {args.command}")
                    return 0
                return run_homekit(args, profile, controller)
            finally:
                controller.close()
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, ValueError, OSError, EOFError) as exc:
        parser.exit(2, f"{parser.prog}: error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
