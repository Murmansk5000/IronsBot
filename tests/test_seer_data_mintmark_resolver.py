import nonebot

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.plugins.seer_data import db


def test_series_ordinal_prefix_rejects_plain_digits() -> None:
    assert not db._is_valid_series_ordinal_prefix("1")
    assert not db._is_valid_series_ordinal_prefix("13")
    assert db._parse_series_ordinal_arg("17") is None


def test_series_ordinal_prefix_accepts_named_series_or_aliases() -> None:
    assert db._is_valid_series_ordinal_prefix("k17")
    assert db._is_valid_series_ordinal_prefix("九霄")
    assert db._is_valid_series_ordinal_prefix("沧吟星海")
    assert db._parse_series_ordinal_arg("k1707") == ("k17", 7)
    assert db._parse_series_ordinal_arg("九霄05") == ("九霄", 5)
