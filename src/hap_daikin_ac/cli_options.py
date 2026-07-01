"""Shared argparse option builders."""

from __future__ import annotations

import argparse
import os

from .cli_env import (
    HOMEKIT_ADDRESS_ENV,
    HOMEKIT_MAX_TEMP_ENV,
    HOMEKIT_MIN_TEMP_ENV,
    HOMEKIT_NAME_ENV,
    HOMEKIT_PINCODE_ENV,
    HOMEKIT_PERSIST_FILE_ENV,
    HOMEKIT_PORT_ENV,
    LOG_LEVEL_ENV,
    RM4_DISCOVER_IP_ENV,
    RM4_HOST_ENV,
    RM4_LOCAL_IP_ENV,
    RM4_MAC_ADDRESS_ENV,
    RM4_MAC_ENV,
    RM4_REPEAT_DELAY_ENV,
    RM4_REPEATS_ENV,
    RM4_TIMEOUT_ENV,
    env_bool,
    env_float,
    env_int,
    env_value,
    rm4_mac_from_env,
)
from .protocol import BASE_STATE, MAX_TEMP_C, MIN_TEMP_C, Mode


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
        "--min-temp",
        type=int,
        default=env_int(HOMEKIT_MIN_TEMP_ENV, MIN_TEMP_C),
        help=f"minimum HomeKit cooling setpoint in C; env {HOMEKIT_MIN_TEMP_ENV}",
    )
    parser.add_argument(
        "--max-temp",
        type=int,
        default=env_int(HOMEKIT_MAX_TEMP_ENV, MAX_TEMP_C),
        help=f"maximum HomeKit cooling setpoint in C; env {HOMEKIT_MAX_TEMP_ENV}",
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
