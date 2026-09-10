from ironsbot.services.seer.rank_formatting import (
    GLOBAL_RANK_MISS_POSITION_STYLE,
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
        == "名次未确认"
    )


def test_zero_limit_is_not_absence_proof() -> None:
    result = RankLookupResult(
        title="群星之巅",
        score_name="群星之巅",
        searched_limit=0,
        queried=True,
    )

    assert format_rank_position_text(result) == "名次未确认"
    assert (
        format_rank_position_text(
            result,
            style=GLOBAL_RANK_MISS_POSITION_STYLE,
        )
        == "名次未确认"
    )
