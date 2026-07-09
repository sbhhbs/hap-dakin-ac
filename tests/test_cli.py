from hap_daikin_ac.cli import build_parser


def test_rm4_mac_address_env_alias(monkeypatch) -> None:
    monkeypatch.delenv("HAP_DAIKIN_RM4_MAC", raising=False)
    monkeypatch.setenv("HAP_DAIKIN_RM4_MAC_ADDRESS", "a0:43:b0:72:bb:64")

    args = build_parser().parse_args(["sensors"])

    assert args.mac == "a0:43:b0:72:bb:64"


def test_short_rm4_mac_env_takes_precedence(monkeypatch) -> None:
    monkeypatch.setenv("HAP_DAIKIN_RM4_MAC", "00:11:22:33:44:55")
    monkeypatch.setenv("HAP_DAIKIN_RM4_MAC_ADDRESS", "a0:43:b0:72:bb:64")

    args = build_parser().parse_args(["sensors"])

    assert args.mac == "00:11:22:33:44:55"


def test_empty_env_values_fall_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setenv("HAP_DAIKIN_HOMEKIT_ADDRESS", "")
    monkeypatch.setenv("HAP_DAIKIN_RM4_HOST", "")
    monkeypatch.setenv("HAP_DAIKIN_RM4_MAC", "")
    monkeypatch.setenv("HAP_DAIKIN_RM4_MAC_ADDRESS", "")
    monkeypatch.setenv("HAP_DAIKIN_RM4_LOCAL_IP", "")
    monkeypatch.setenv("HAP_DAIKIN_RM4_DISCOVER_IP", "")
    monkeypatch.setenv("HAP_DAIKIN_HOMEKIT_PORT", "")
    monkeypatch.setenv("HAP_DAIKIN_SENSOR_INTERVAL", "")
    monkeypatch.setenv("HAP_DAIKIN_MIN_TEMP", "")
    monkeypatch.setenv("HAP_DAIKIN_MAX_TEMP", "")
    monkeypatch.setenv("HAP_DAIKIN_LOGSTASH_URL", "")
    monkeypatch.setenv("HAP_DAIKIN_LOGSTASH_TIMEOUT", "")

    args = build_parser().parse_args(["homekit"])

    assert args.address is None
    assert args.host is None
    assert args.mac is None
    assert args.local_ip is None
    assert args.discover_ip is None
    assert args.port == 51234
    assert args.sensor_interval == 60
    assert args.min_temp == 10
    assert args.max_temp == 30
    assert args.logstash_url is None
    assert args.logstash_timeout == 3


def test_broadlink_target_env_defaults(monkeypatch) -> None:
    monkeypatch.setenv("HAP_DAIKIN_RM4_TIMEOUT", "9")
    monkeypatch.setenv("HAP_DAIKIN_RM4_LOCAL_IP", "192.168.1.20")
    monkeypatch.setenv("HAP_DAIKIN_RM4_DISCOVER_IP", "192.168.1.255")
    monkeypatch.setenv("HAP_DAIKIN_RM4_REPEATS", "3")
    monkeypatch.setenv("HAP_DAIKIN_RM4_REPEAT_DELAY", "0.2")

    args = build_parser().parse_args(["homekit"])

    assert args.timeout == 9
    assert args.local_ip == "192.168.1.20"
    assert args.discover_ip == "192.168.1.255"
    assert args.repeats == 3
    assert args.repeat_delay == 0.2


def test_homekit_temperature_range_env_defaults(monkeypatch) -> None:
    monkeypatch.setenv("HAP_DAIKIN_MIN_TEMP", "18")
    monkeypatch.setenv("HAP_DAIKIN_MAX_TEMP", "28")

    args = build_parser().parse_args(["homekit"])

    assert args.min_temp == 18
    assert args.max_temp == 28


def test_homekit_logstash_env_defaults(monkeypatch) -> None:
    monkeypatch.setenv("HAP_DAIKIN_LOGSTASH_URL", "logstash:8080")
    monkeypatch.setenv("HAP_DAIKIN_LOGSTASH_TIMEOUT", "1.5")

    args = build_parser().parse_args(["homekit"])

    assert args.logstash_url == "logstash:8080"
    assert args.logstash_timeout == 1.5
