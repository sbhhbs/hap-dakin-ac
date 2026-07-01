"""Environment variable helpers for the CLI."""

from __future__ import annotations

import os

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
