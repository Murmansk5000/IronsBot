from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

from ironsbot.services.seer import rank_display

GROUP_ID = 987654321
USER_ID = 1234567890
STORED_LIMIT = 50
ALIAS_LIMIT = 30


def _rank_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        display_limit=10,
        max_display_limit=100,
        display_limits={},
        display_limit_path=tmp_path / "rank_display.sqlite",
    )


def test_rank_display_limit_prefers_stored_group_limit(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        seer=SimpleNamespace(rank=_rank_config(tmp_path)),
        feature=SimpleNamespace(group_aliases={}),
    )
    monkeypatch.setattr(rank_display, "get_app_config", lambda: config)

    rank_display.set_group_rank_display_limit(
        group_id=GROUP_ID,
        user_id=USER_ID,
        limit=STORED_LIMIT,
    )

    assert rank_display.rank_display_limit_for_group(GROUP_ID) == STORED_LIMIT


def test_rank_display_limit_uses_configured_alias(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    rank_config = _rank_config(tmp_path)
    rank_config.display_limits = {"example": ALIAS_LIMIT}
    config = SimpleNamespace(
        seer=SimpleNamespace(rank=rank_config),
        feature=SimpleNamespace(group_aliases={"example": GROUP_ID}),
    )
    monkeypatch.setattr(rank_display, "get_app_config", lambda: config)

    assert rank_display.rank_display_limit_for_group(GROUP_ID) == ALIAS_LIMIT
