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
