# SPDX-License-Identifier: MIT
from ironsbot.core.commands import normalize_command_text
from ironsbot.core.text_matching import TextMatchRule
from ironsbot.integrations.seer_data.normalization import normalize_key


def test_exact_names_and_aliases_exclude_partial_candidates() -> None:
    labels = {
        1: ("星光之主", "星光"),
        2: ("星光", "光明"),
        3: ("星光之影", "光影"),
    }
    rule = TextMatchRule(normalize_key)
    result = rule.select("星 光", labels, names=labels.__getitem__)
    assert result.kind == "exact" and result.matches == (1, 2)
    partial = rule.select("之", labels, names=labels.__getitem__)
    assert partial.kind == "partial" and partial.matches == (1, 3)
    alias = rule.select("光明", labels, names=labels.__getitem__)
    assert alias.kind == "exact" and alias.matches == (2,)


def test_whole_argument_normalization_and_empty_guard() -> None:
    rule = TextMatchRule(normalize_key)
    candidates = ("Star-Light", "星光")
    assert rule.select(
        "STAR · LIGHT", candidates, names=lambda value: (value,)
    ).matches == ("Star-Light",)
    for query in ("", " · _ - / ", "星光没拿好也是卒"):
        assert (
            rule.select(query, candidates, names=lambda value: (value,)).kind == "none"
        )
    assert (
        rule.select(
            "Star", candidates, names=lambda value: (value,), allow_partial=False
        ).kind
        == "none"
    )


def test_fixed_keywords_use_full_text_and_sql_patterns_escape_metacharacters() -> None:
    rule = TextMatchRule(normalize_command_text)
    assert rule.matches_any("HELP ", ("help", "帮助"))
    assert not rule.matches_any("今天help没用", ("help", "帮助"))
    assert rule.contains_pattern("A%_\\B") == "%a\\%\\_\\\\b%"
