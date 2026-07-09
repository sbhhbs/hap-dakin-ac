import json

from hap_daikin_ac.rm4 import Rm4SensorReadings
from hap_daikin_ac.telemetry import (
    LogstashTelemetryClient,
    build_sensor_event,
    normalize_logstash_url,
)


def test_normalize_logstash_url_adds_http_scheme() -> None:
    assert normalize_logstash_url("logstash:8080") == "http://logstash:8080"
    assert normalize_logstash_url("https://example.test/input") == (
        "https://example.test/input"
    )
    assert normalize_logstash_url("") is None


def test_build_sensor_event_includes_reading_and_metadata() -> None:
    event = build_sensor_event(
        Rm4SensorReadings(
            temperature=26.4,
            humidity=61.2,
            raw={"temperature": 26.4, "humidity": 61.2},
        ),
        metadata={
            "accessory_name": "Daikin AC",
            "rm4_host": "192.168.1.50",
            "rm4_mac": "a043b0b9f7f6",
            "empty": "",
        },
    )

    assert event["service_name"] == "hap-daikin-ac"
    assert event["event_type"] == "rm4_sensor_reading"
    assert event["temperature_c"] == 26.4
    assert event["humidity_percent"] == 61.2
    assert event["accessory_name"] == "Daikin AC"
    assert event["rm4_host"] == "192.168.1.50"
    assert event["rm4_mac"] == "a043b0b9f7f6"
    assert event["raw"] == {"temperature": 26.4, "humidity": 61.2}
    assert "timestamp" in event
    assert "container_hostname" in event
    assert "empty" not in event


def test_logstash_telemetry_client_posts_json(monkeypatch) -> None:
    captured = {}

    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def fake_urlopen(http_request, timeout):
        captured["url"] = http_request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(http_request.data.decode("utf-8"))
        captured["content_type"] = http_request.headers["Content-type"]
        return Response()

    monkeypatch.setattr("hap_daikin_ac.telemetry.request.urlopen", fake_urlopen)

    client = LogstashTelemetryClient("logstash:8080", timeout=1.5)
    client.send_sensor_reading(
        Rm4SensorReadings(temperature=25.1, humidity=59.0),
        metadata={"accessory_name": "Test AC"},
    )

    assert captured["url"] == "http://logstash:8080"
    assert captured["timeout"] == 1.5
    assert captured["content_type"] == "application/json"
    assert captured["body"]["temperature_c"] == 25.1
    assert captured["body"]["humidity_percent"] == 59.0
    assert captured["body"]["accessory_name"] == "Test AC"
