"""Broadlink RM4 discovery and send helpers."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any


@dataclass(frozen=True)
class Rm4SensorReadings:
    temperature: float | None = None
    humidity: float | None = None
    raw: dict[str, Any] | None = None


def normalize_mac(value: str) -> str:
    normalized = "".join(ch for ch in value.lower() if ch in "0123456789abcdef")
    if len(normalized) != 12:
        raise ValueError("MAC address must contain 12 hex digits")
    return normalized


def reverse_mac(value: str) -> str:
    return bytes.fromhex(value)[::-1].hex()


def device_mac_hex(device: Any) -> str:
    mac = getattr(device, "mac", b"")
    if isinstance(mac, str):
        return normalize_mac(mac)
    return bytes(mac).hex()


def device_summary(device: Any) -> str:
    host = getattr(device, "host", ("unknown", None))
    address = host[0] if isinstance(host, tuple) else str(host)
    model = getattr(device, "model", device.__class__.__name__)
    locked = getattr(device, "is_locked", None)
    locked_text = "" if locked is None else f" locked={locked}"
    return f"{model} host={address} mac={device_mac_hex(device)}{locked_text}"


def mac_matches(device: Any, mac: str) -> bool:
    target = normalize_mac(mac)
    actual = device_mac_hex(device)
    return actual == target or reverse_mac(actual) == target


def discover_devices(
    *,
    timeout: int = 5,
    local_ip_address: str | None = None,
    discover_ip_address: str | None = None,
) -> list[Any]:
    import broadlink
    from broadlink.exceptions import BroadlinkException

    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "local_ip_address": local_ip_address,
    }
    if discover_ip_address:
        kwargs["discover_ip_address"] = discover_ip_address
    try:
        return broadlink.discover(**kwargs)
    except BroadlinkException as exc:
        raise RuntimeError(f"Broadlink discovery failed: {exc}") from exc


def select_device(
    *,
    host: str | None = None,
    mac: str | None = None,
    timeout: int = 5,
    local_ip_address: str | None = None,
    discover_ip_address: str | None = None,
) -> Any:
    import broadlink
    from broadlink.exceptions import BroadlinkException

    if host:
        try:
            device = broadlink.hello(host, timeout=timeout)
        except BroadlinkException as exc:
            raise RuntimeError(f"Broadlink discovery failed for {host}: {exc}") from exc
        if mac and not mac_matches(device, mac):
            raise RuntimeError(
                f"device at {host} has MAC {device_mac_hex(device)}, not {mac}"
            )
        if not hasattr(device, "send_data"):
            raise RuntimeError(f"device at {host} is not a Broadlink RM remote")
        return device

    devices = [
        device
        for device in discover_devices(
            timeout=timeout,
            local_ip_address=local_ip_address,
            discover_ip_address=discover_ip_address,
        )
        if hasattr(device, "send_data")
    ]

    if mac:
        target_mac = normalize_mac(mac)
        devices = [device for device in devices if mac_matches(device, target_mac)]

    if not devices:
        if mac:
            raise RuntimeError(
                f"no Broadlink RM device found matching MAC {normalize_mac(mac)}"
            )
        raise RuntimeError("no Broadlink RM device found")
    if len(devices) > 1:
        summaries = "\n".join(f"  - {device_summary(device)}" for device in devices)
        raise RuntimeError(f"multiple Broadlink RM devices found:\n{summaries}")
    return devices[0]


def authenticate_device(device: Any) -> None:
    from broadlink.exceptions import BroadlinkException

    try:
        device.auth()
    except BroadlinkException as exc:
        raise RuntimeError(f"Broadlink authentication failed: {exc}") from exc


def send_ir_packet_to_device(
    device: Any,
    packet: bytes,
    *,
    repeats: int = 1,
    repeat_delay: float = 0.4,
) -> None:
    from broadlink.exceptions import BroadlinkException

    if repeats < 1:
        raise ValueError("repeats must be at least 1")

    try:
        for index in range(repeats):
            device.send_data(packet)
            if index < repeats - 1:
                time.sleep(repeat_delay)
    except BroadlinkException as exc:
        raise RuntimeError(f"Broadlink send failed: {exc}") from exc


def read_device_sensors(device: Any) -> Rm4SensorReadings:
    from broadlink.exceptions import BroadlinkException

    if not hasattr(device, "check_sensors"):
        raise RuntimeError(f"{device_summary(device)} does not expose RM4 sensors")

    try:
        raw = device.check_sensors()
    except BroadlinkException as exc:
        raise RuntimeError(f"Broadlink sensor read failed: {exc}") from exc

    temperature = raw.get("temperature")
    humidity = raw.get("humidity")
    return Rm4SensorReadings(
        temperature=float(temperature) if temperature is not None else None,
        humidity=float(humidity) if humidity is not None else None,
        raw=raw,
    )


def send_ir_packet(
    packet: bytes,
    *,
    host: str | None = None,
    mac: str | None = None,
    timeout: int = 5,
    repeats: int = 1,
    repeat_delay: float = 0.4,
    local_ip_address: str | None = None,
    discover_ip_address: str | None = None,
) -> Any:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")

    device = select_device(
        host=host,
        mac=mac,
        timeout=timeout,
        local_ip_address=local_ip_address,
        discover_ip_address=discover_ip_address,
    )
    authenticate_device(device)
    send_ir_packet_to_device(
        device,
        packet,
        repeats=repeats,
        repeat_delay=repeat_delay,
    )
    return device


def read_sensors(
    *,
    host: str | None = None,
    mac: str | None = None,
    timeout: int = 5,
    local_ip_address: str | None = None,
    discover_ip_address: str | None = None,
) -> Rm4SensorReadings:
    device = select_device(
        host=host,
        mac=mac,
        timeout=timeout,
        local_ip_address=local_ip_address,
        discover_ip_address=discover_ip_address,
    )
    authenticate_device(device)
    return read_device_sensors(device)
