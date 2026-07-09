from ironsbot.services.seer.rank_formatting import (
    GLOBAL_RANK_MISS_POSITION_STYLE,
    RANK_LOOKUP_POSITION_STYLE,
    format_peak_rank_lookup,
    format_rank_position_text,
)
from ironsbot.services.seer.rank_models import RankLookupResult


def test_format_rank_position_text_defaults_to_global_summary() -> None:
    assert (
        format_rank_position_text(
            RankLookupResult(
                title="图鉴积分",
                score_name="图鉴积分",
                rank=12,
                score=1234,
                queried=True,
            )
        )
        == "全服第12"
    )

    assert (
        format_rank_position_text(
            RankLookupResult(
                title="图鉴积分",
                score_name="图鉴积分",
                searched_limit=2000,
                queried=True,
            )
        )
        == "全服未进入前2000"
    )


def test_format_rank_position_text_supports_rank_lookup_style() -> None:
    result = RankLookupResult(
        title="群星之巅",
        score_name="群星之巅",
        searched_limit=2000,
        queried=True,
    )

    assert (
        format_rank_position_text(
            result,
            style=RANK_LOOKUP_POSITION_STYLE,
        )
        == "前 2000 名未上榜"
    )


def test_format_rank_position_text_can_keep_zero_limit_for_existing_messages() -> None:
    result = RankLookupResult(
        title="群星之巅",
        score_name="群星之巅",
        searched_limit=0,
        queried=True,
    )

    assert format_rank_position_text(result) == ""
    assert (
        format_rank_position_text(
            result,
            style=GLOBAL_RANK_MISS_POSITION_STYLE,
        )
        == "前 0 名未上榜"
    )


def test_format_peak_rank_lookup_keeps_existing_position_text() -> None:
    assert (
        format_peak_rank_lookup(
            RankLookupResult(
                title="竞技赛季榜",
                score_name="段位分",
                rank=7,
                score=1234,
                queried=True,
            ),
            inactive_text="未参赛",
        )
        == "第 7 名"
    )

    assert (
        format_peak_rank_lookup(
            RankLookupResult(
                title="竞技赛季榜",
                score_name="段位分",
                searched_limit=500,
                queried=True,
            ),
            inactive_text="未参赛",
        )
        == "前 500 名未上榜"
    )
