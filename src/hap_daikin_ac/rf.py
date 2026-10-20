"""Learned RF profiles and transmission through a Broadlink RM Pro."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import socket
import sys
from threading import Lock
import time

from broadlink.exceptions import BroadlinkException, ReadError, StorageError

from .rm4 import authenticate_device, normalize_mac, select_device
from .rf_protocol import COMMAND_NIBBLES, Fixed24Packet, normalize_prefix

LOGGER = logging.getLogger(__name__)
COMMANDS = ("fan_off", "fan_high", "fan_mid", "fan_low", "light_toggle")
RF_TYPES = {0xB1, 0xB2, 0xB4, 0xD7}


def validate_frequency(frequency: float) -> None:
    if not math.isfinite(frequency) or not 0 < frequency < 1000:
        raise ValueError("RF frequency must be a positive MHz value below 1000")


def default_profile_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/hap-daikin-ac/rf-fan-light/codes.json"
    return Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "hap-rf-fan/codes.json"


def validate_rf_packet(packet: bytes) -> None:
    if len(packet) < 8 or packet[0] not in RF_TYPES:
        raise ValueError("expected a learned Broadlink RF packet")
    declared = int.from_bytes(packet[2:4], "little")
    if declared == 0 or declared + 4 > len(packet):
        raise ValueError("truncated Broadlink RF packet")


@dataclass
class RfProfile:
    name: str = "Ceiling Fan"
    frequency_mhz: float = 433.86
    rm4_host: str | None = None
    rm4_mac: str | None = None
    codes: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("RF profile name must be a non-empty string")
        validate_frequency(self.frequency_mhz)
        if self.rm4_host is not None and not isinstance(self.rm4_host, str):
            raise ValueError("RM4 host must be a string")
        if self.rm4_mac is not None:
            if not isinstance(self.rm4_mac, str):
                raise ValueError("RM4 MAC must be a string")
            normalize_mac(self.rm4_mac)

    @classmethod
    def load(cls, path: Path) -> RfProfile:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f"unable to read RF profile {path}: {exc}") from exc
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("unsupported RF profile version")
        if not isinstance(data.get("codes"), dict):
            raise ValueError("RF profile must contain a codes object")
        codes = {}
        for name, code in data["codes"].items():
            if name not in COMMANDS or not isinstance(code, str):
                raise ValueError(f"invalid RF command: {name}")
            packet = bytes.fromhex(code)
            validate_rf_packet(packet)
            codes[name] = packet
        profile = cls(
            name=data.get("name", "Ceiling Fan"),
            frequency_mhz=float(data.get("frequency_mhz", 433.86)),
            rm4_host=data.get("rm4_host"),
            rm4_mac=data.get("rm4_mac"),
            codes=codes,
        )
        return profile

    def require_complete(self) -> None:
        missing = set(COMMANDS) - self.codes.keys()
        if missing:
            raise ValueError(f"missing learned RF commands: {', '.join(sorted(missing))}")

    def packet(self, command: str) -> bytes:
        if command not in COMMANDS:
            raise ValueError(f"unknown RF command: {command}")
        if command not in self.codes:
            raise ValueError(f"learn {command} before sending it")
        packet = self.codes[command]
        validate_rf_packet(packet)
        return packet

    def with_rf_overrides(
        self, *, prefix: str | None = None, frequency_mhz: float | None = None,
    ) -> RfProfile:
        """Build packets in memory; leave the original learned profile intact."""
        if prefix is None and frequency_mhz is None:
            return self
        if prefix is not None:
            prefix = normalize_prefix(prefix)
        if frequency_mhz is not None:
            validate_frequency(frequency_mhz)
        if not self.codes:
            raise ValueError("learn RF commands before applying overrides")
        decoded = {name: Fixed24Packet.decode(packet) for name, packet in self.codes.items()}
        if len({packet.prefix for packet in decoded.values()}) != 1:
            raise ValueError("RF templates must all belong to the same fan address")
        for name, packet in decoded.items():
            if packet.word & 0xF != COMMAND_NIBBLES.get(name):
                raise ValueError(f"RF {name} does not match the observed fan command format")
        return replace(
            self,
            frequency_mhz=self.frequency_mhz if frequency_mhz is None else frequency_mhz,
            codes={name: packet.rewrite(prefix=prefix, frequency_mhz=frequency_mhz)
                   for name, packet in decoded.items()},
        )

    def save(self, path: Path) -> None:
        data = {
            "version": 1, "name": self.name, "frequency_mhz": self.frequency_mhz,
            "rm4_host": self.rm4_host, "rm4_mac": self.rm4_mac,
            "codes": {name: code.hex() for name, code in self.codes.items()},
            "last_captured_at": datetime.now(timezone.utc).isoformat(),
        }
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(data, output, indent=2)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def broadlink_interface(interface: str | None):
    """Scope Broadlink sockets for this dedicated CLI process on macOS.

    broadlink 0.19 creates sockets internally and has no interface option. Swap
    only its socket namespace for the lifetime of the CLI, not Python's global
    socket factory. Enter before starting workers and leave after they stop.
    """
    if not interface:
        yield
        return
    if sys.platform != "darwin":
        raise ValueError("--interface currently supports macOS only")
    interface_index = socket.if_nametoindex(interface)
    import broadlink.device as device_module

    class ScopedSockets:
        def __getattr__(self, name):
            return getattr(socket, name)

        def socket(self, *args, **kwargs):
            conn = socket.socket(*args, **kwargs)
            try:
                if conn.family == socket.AF_INET and conn.type == socket.SOCK_DGRAM:
                    conn.setsockopt(socket.IPPROTO_IP, 25, interface_index)
                return conn
            except BaseException:
                conn.close()
                raise

    original = device_module.socket
    device_module.socket = ScopedSockets()
    try:
        yield
    finally:
        device_module.socket = original


class RfController:
    def __init__(
        self, profile: RfProfile, *, host: str | None = None,
        mac: str | None = None, timeout: float = 3, dry_run: bool = False,
    ) -> None:
        self.profile = profile
        self.host = host or profile.rm4_host
        self.mac = mac or profile.rm4_mac
        self.timeout = timeout
        self.dry_run = dry_run
        self._device = None
        self._lock = Lock()

    def connect(self) -> None:
        with self._lock:
            if self.dry_run or self._device is not None:
                return
            device = select_device(host=self.host, mac=self.mac, timeout=self.timeout)
            if not hasattr(device, "find_rf_packet"):
                raise ValueError("selected Broadlink device does not support RF")
            device.timeout = self.timeout
            authenticate_device(device)
            self._device = device

    def close(self) -> None:
        with self._lock:
            self._device = None

    def send(self, command: str) -> None:
        packet = self.profile.packet(command)
        if self.dry_run:
            LOGGER.info("dry-run RF command: %s (%s bytes)", command, len(packet))
            return
        self.connect()
        with self._lock:
            if self._device is None:
                raise RuntimeError("RF controller is closed")
            old_timeout = self._device.timeout
            try:
                # A light toggle must never be retransmitted automatically.
                # Bound the wait below broadlink's one-second retry interval.
                if command == "light_toggle":
                    self._device.timeout = min(old_timeout, 0.8)
                self._device.send_data(packet)
            except (BroadlinkException, OSError) as exc:
                suffix = "; delivery uncertain, toggle was not retried" if command == "light_toggle" else ""
                raise RuntimeError(f"RF {command} failed: {exc}{suffix}") from exc
            finally:
                self._device.timeout = old_timeout
        LOGGER.info("sent RF command: %s", command)

    def learn(self, *, timeout: float = 60, ready=None) -> bytes:
        if timeout <= 0:
            raise ValueError("learning timeout must be positive")
        validate_frequency(self.profile.frequency_mhz)
        self.connect()
        if self.dry_run:
            raise ValueError("RF learning requires a real device")
        with self._lock:
            try:
                self._device.find_rf_packet(self.profile.frequency_mhz)
                if ready:
                    ready()
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    time.sleep(0.4)
                    try:
                        packet = self._device.check_data()
                    except (ReadError, StorageError):
                        continue
                    if packet:
                        validate_rf_packet(packet)
                        return packet
                raise TimeoutError("no RF code received before learning timed out")
            finally:
                try:
                    self._device.cancel_sweep_frequency()
                except (BroadlinkException, OSError) as exc:
                    LOGGER.warning("unable to exit RF learning mode: %s", exc)
