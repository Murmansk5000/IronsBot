from ironsbot.services.seer.local_rank_formatting import format_metric_display


def test_format_metric_display_decodes_peak_scores() -> None:
    assert format_metric_display("peak_standard", 400036) == "圣皇36星"
    assert format_metric_display("peak_wild", 300065) == "王者65星"
    assert format_metric_display("peak_expert", 1155) == "1155分"


def test_format_metric_display_keeps_cached_display_text() -> None:
    assert format_metric_display("peak_standard", 400036, "圣皇36星") == "圣皇36星"
    assert format_metric_display("book_score", 12345) == "12345"
