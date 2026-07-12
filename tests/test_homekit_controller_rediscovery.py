from __future__ import annotations

import logging
from threading import Event, Lock, Thread, current_thread
import time

import pytest

from hap_daikin_ac.homekit_controller import (
    BroadlinkDaikinController,
    BroadlinkTarget,
)
from hap_daikin_ac.rm4 import Rm4ConnectivityError, Rm4SensorReadings


MAC = "a0:43:b0:b9:f7:f6"


class FakeDevice:
    def __init__(self, ip_address: str) -> None:
        self.host = (ip_address, 80)
        self.mac = bytes.fromhex(MAC.replace(":", ""))
        self.model = "RM4 mini"


class PauseReaderAfterReleaseLock:
    """Let a rebind finish after a sensor reader releases the device lock."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.reader_released = Event()
        self.resume_reader = Event()

    def __enter__(self) -> "PauseReaderAfterReleaseLock":
        self._lock.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self._lock.release()
        if current_thread().name == "stale-sensor-reader":
            self.reader_released.set()
            if not self.resume_reader.wait(timeout=2.0):
                raise RuntimeError("test did not resume sensor reader")


def _controller(
    device: FakeDevice,
    *,
    host: str | None = None,
    sensor_cache_ttl: float = 0,
) -> BroadlinkDaikinController:
    controller = BroadlinkDaikinController(
        BroadlinkTarget(
            host=host,
            mac=MAC,
            timeout=9,
            local_ip_address="192.168.10.20",
            discover_ip_address="192.168.10.255",
            sensor_cache_ttl=sensor_cache_ttl,
        )
    )
    controller._device = device
    return controller


def _join_rediscovery(
    controller: BroadlinkDaikinController,
    *,
    timeout: float = 2.0,
) -> None:
    thread = controller._rediscovery_thread
    assert thread is not None
    assert thread.daemon
    thread.join(timeout=timeout)
    assert not thread.is_alive(), "rediscovery worker did not finish"


def test_connectivity_failure_rediscovery_rebinds_controller(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    old_device = FakeDevice("192.168.10.40")
    replacement = FakeDevice("192.168.10.91")
    controller = _controller(old_device, sensor_cache_ttl=300)
    controller._sensor_cache = Rm4SensorReadings(temperature=20, humidity=40)
    controller._sensor_cache_at = time.monotonic()
    failure = Rm4ConnectivityError("sensor request timed out")
    discovery_started = Event()
    select_calls: list[dict[str, object]] = []
    authenticated: list[FakeDevice] = []
    read_devices: list[FakeDevice] = []

    def fake_read_device_sensors(device: FakeDevice) -> Rm4SensorReadings:
        read_devices.append(device)
        if device is old_device:
            raise failure
        return Rm4SensorReadings(
            temperature=24.5,
            humidity=58.0,
            raw={"temperature": 24.5, "humidity": 58},
        )

    def fake_select_device(**kwargs: object) -> FakeDevice:
        select_calls.append(kwargs)
        discovery_started.set()
        return replacement

    def fake_authenticate_device(device: FakeDevice) -> None:
        authenticated.append(device)

    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.read_device_sensors",
        fake_read_device_sensors,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.select_device",
        fake_select_device,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.authenticate_device",
        fake_authenticate_device,
    )
    caplog.set_level(logging.DEBUG, logger="hap_daikin_ac.homekit_controller")

    with pytest.raises(Rm4ConnectivityError) as raised:
        controller.read_sensors(force=True)

    assert raised.value is failure
    assert discovery_started.wait(timeout=1.0)
    _join_rediscovery(controller)
    assert select_calls == [
        {
            "host": None,
            "mac": MAC,
            "timeout": 9,
            "local_ip_address": "192.168.10.20",
            "discover_ip_address": "192.168.10.255",
        }
    ]
    assert authenticated == [replacement]
    assert controller._device is replacement

    readings = controller.read_sensors()

    assert readings == Rm4SensorReadings(
        temperature=24.5,
        humidity=58.0,
        raw={"temperature": 24.5, "humidity": 58},
    )
    assert read_devices == [old_device, replacement]
    assert controller.device_metadata() == {
        "rm4_configured_mac": MAC,
        "rm4_host": "192.168.10.91",
        "rm4_mac": "a043b0b9f7f6",
        "rm4_model": "RM4 mini",
    }
    assert "scheduling background rediscovery" in caplog.text
    assert "192.168.10.40" in caplog.text
    assert "192.168.10.91" in caplog.text
    assert "rebound RM4 controller" in caplog.text


def test_duplicate_failures_start_only_one_rediscovery_worker(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    old_device = FakeDevice("192.168.10.40")
    replacement = FakeDevice("192.168.10.91")
    controller = _controller(old_device)
    discovery_started = Event()
    release_discovery = Event()
    select_calls: list[dict[str, object]] = []

    def fail_sensor_read(device: FakeDevice) -> Rm4SensorReadings:
        assert device is old_device
        raise Rm4ConnectivityError("device offline")

    def blocking_select_device(**kwargs: object) -> FakeDevice:
        select_calls.append(kwargs)
        discovery_started.set()
        if not release_discovery.wait(timeout=2.0):
            raise RuntimeError("test did not release discovery worker")
        return replacement

    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.read_device_sensors",
        fail_sensor_read,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.select_device",
        blocking_select_device,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.authenticate_device",
        lambda device: None,
    )
    caplog.set_level(logging.DEBUG, logger="hap_daikin_ac.homekit_controller")

    with pytest.raises(Rm4ConnectivityError):
        controller.read_sensors(force=True)

    try:
        assert discovery_started.wait(timeout=1.0)
        with pytest.raises(Rm4ConnectivityError):
            controller.read_sensors(force=True)
        assert len(select_calls) == 1
        assert "rediscovery is already running" in caplog.text
    finally:
        release_discovery.set()
        _join_rediscovery(controller)


def test_failed_rediscovery_keeps_old_device_and_next_failure_retries(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    old_device = FakeDevice("192.168.10.40")
    replacement = FakeDevice("192.168.10.91")
    controller = _controller(old_device)
    attempts: list[dict[str, object]] = []
    authenticated: list[FakeDevice] = []

    def fail_sensor_read(device: FakeDevice) -> Rm4SensorReadings:
        assert device is old_device
        raise Rm4ConnectivityError("device offline")

    def flaky_select_device(**kwargs: object) -> FakeDevice:
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("nothing found")
        return replacement

    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.read_device_sensors",
        fail_sensor_read,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.select_device",
        flaky_select_device,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.authenticate_device",
        authenticated.append,
    )
    caplog.set_level(logging.DEBUG, logger="hap_daikin_ac.homekit_controller")

    with pytest.raises(Rm4ConnectivityError):
        controller.read_sensors(force=True)
    _join_rediscovery(controller)

    first_thread = controller._rediscovery_thread
    assert controller._device is old_device
    assert len(attempts) == 1
    assert authenticated == []
    assert "the next sensor connectivity failure will retry" in caplog.text

    with pytest.raises(Rm4ConnectivityError):
        controller.read_sensors(force=True)
    _join_rediscovery(controller)

    assert controller._rediscovery_thread is not first_thread
    assert len(attempts) == 2
    assert authenticated == [replacement]
    assert controller._device is replacement


def test_rebind_cannot_leave_old_device_readings_in_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_device = FakeDevice("192.168.10.40")
    replacement = FakeDevice("192.168.10.91")
    old_readings = Rm4SensorReadings(temperature=20, humidity=40)
    new_readings = Rm4SensorReadings(temperature=25, humidity=55)
    controller = _controller(old_device, sensor_cache_ttl=300)
    coordinated_lock = PauseReaderAfterReleaseLock()
    controller._device_lock = coordinated_lock
    read_devices: list[FakeDevice] = []
    results: list[Rm4SensorReadings | None] = []

    def fake_read_device_sensors(device: FakeDevice) -> Rm4SensorReadings:
        read_devices.append(device)
        return old_readings if device is old_device else new_readings

    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.read_device_sensors",
        fake_read_device_sensors,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.select_device",
        lambda **kwargs: replacement,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.authenticate_device",
        lambda device: None,
    )

    reader = Thread(
        target=lambda: results.append(controller.read_sensors(force=True)),
        name="stale-sensor-reader",
        daemon=True,
    )
    reader.start()
    try:
        assert coordinated_lock.reader_released.wait(timeout=1.0)
        controller._rediscover_device(old_device)
    finally:
        coordinated_lock.resume_reader.set()
    reader.join(timeout=1.0)

    assert not reader.is_alive()
    assert results == [old_readings]
    assert controller._device is replacement
    assert controller._sensor_cache is None
    assert controller.read_sensors() == new_readings
    assert read_devices == [old_device, replacement]


def test_ordinary_sensor_error_does_not_start_rediscovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_device = FakeDevice("192.168.10.40")
    controller = _controller(old_device)
    select_calls: list[dict[str, object]] = []

    def fail_sensor_read(device: FakeDevice) -> Rm4SensorReadings:
        raise RuntimeError("sensor payload is malformed")

    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.read_device_sensors",
        fail_sensor_read,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.select_device",
        lambda **kwargs: select_calls.append(kwargs),
    )

    with pytest.raises(RuntimeError, match="sensor payload is malformed"):
        controller.read_sensors(force=True)

    assert controller._rediscovery_thread is None
    assert select_calls == []
    assert controller._device is old_device


def test_fixed_host_connectivity_failure_does_not_start_rediscovery(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    old_device = FakeDevice("192.168.10.40")
    controller = _controller(old_device, host="192.168.10.40")
    select_calls: list[dict[str, object]] = []

    def fail_sensor_read(device: FakeDevice) -> Rm4SensorReadings:
        raise Rm4ConnectivityError("device offline")

    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.read_device_sensors",
        fail_sensor_read,
    )
    monkeypatch.setattr(
        "hap_daikin_ac.homekit_controller.select_device",
        lambda **kwargs: select_calls.append(kwargs),
    )
    caplog.set_level(logging.DEBUG, logger="hap_daikin_ac.homekit_controller")

    with pytest.raises(Rm4ConnectivityError, match="device offline"):
        controller.read_sensors(force=True)

    assert controller._rediscovery_thread is None
    assert select_calls == []
    assert controller._device is old_device
    assert "rediscovery skipped" in caplog.text
