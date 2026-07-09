from ironsbot.integrations.seer_data import mintmark_series_resolvers as resolvers


def test_series_ordinal_prefix_rejects_plain_digits() -> None:
    assert not resolvers._is_valid_series_ordinal_prefix("1")
    assert not resolvers._is_valid_series_ordinal_prefix("13")
    assert resolvers._parse_series_ordinal_arg("17") is None


def test_series_ordinal_prefix_accepts_named_series_or_aliases() -> None:
    assert resolvers._is_valid_series_ordinal_prefix("k17")
    assert resolvers._is_valid_series_ordinal_prefix("九霄")
    assert resolvers._is_valid_series_ordinal_prefix("沧吟星海")
    assert resolvers._parse_series_ordinal_arg("k1707") == ("k17", 7)
    assert resolvers._parse_series_ordinal_arg("九霄05") == ("九霄", 5)
