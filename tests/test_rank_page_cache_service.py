from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

from ironsbot.services.seer import rank_page_cache
from ironsbot.services.seer.rank_page_cache import (
    get_cached_rank_item,
    get_rank_page_cache_summary,
    save_rank_page,
)

MOVED_RANK_INDEX = 100
MOVED_SCORE = 1001


def test_save_rank_page_deduplicates_user_within_same_rank(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "rank_page_cache.sqlite"
    monkeypatch.setattr(
        rank_page_cache,
        "get_rank_query_config",
        lambda: SimpleNamespace(
            page_cache=True,
            page_cache_path=cache_path,
            page_cache_ttl_seconds=3600,
            allow_stale_cache=True,
        ),
    )

    save_rank_page(
        key=1,
        sub_key=2,
        start=0,
        end=99,
        items=[SimpleNamespace(id=100, nick="旧名", score=999)],
    )
    save_rank_page(
        key=1,
        sub_key=2,
        start=100,
        end=199,
        items=[SimpleNamespace(id=100, nick="新名", score=1001)],
    )

    cached = get_cached_rank_item(key=1, sub_key=2, user_id=100)
    assert cached is not None
    assert cached.rank_index == MOVED_RANK_INDEX
    assert cached.nick == "新名"
    assert cached.score == MOVED_SCORE

    summaries = get_rank_page_cache_summary(key=1, sub_key=2)
    actual = [
        (page.start_index, page.item_count, page.expected_count, page.is_partial)
        for page in summaries
    ]
    assert actual == [
        (0, 0, 1, True),
        (100, 1, 1, False),
    ]
