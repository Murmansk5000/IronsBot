from ironsbot.services.seer.local_rank_formatting import format_metric_display
from ironsbot.services.seer.value_coercion import coerce_positive_int

EXPECTED_POSITIVE_INT = 12


def test_coerce_positive_int_rejects_invalid_and_non_positive_values() -> None:
    assert coerce_positive_int(str(EXPECTED_POSITIVE_INT)) == EXPECTED_POSITIVE_INT
    assert coerce_positive_int(0) is None
    assert coerce_positive_int(-1) is None
    assert coerce_positive_int("invalid") is None


def test_format_metric_display_decodes_peak_scores() -> None:
    assert format_metric_display("peak_standard", 400036) == "圣皇36星"
    assert format_metric_display("peak_standard", 400100) == "宇宙圣皇100星"
    assert format_metric_display("peak_wild", 300065) == "王者65星"
    assert format_metric_display("peak_expert", 1155) == "1155分"


def test_format_metric_display_keeps_cached_display_text() -> None:
    assert format_metric_display("peak_standard", 400036, "圣皇36星") == "圣皇36星"
    assert format_metric_display("book_score", 12345) == "12345"
