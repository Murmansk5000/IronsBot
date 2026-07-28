import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from ironsbot.services.seer.local_rank_models import LocalRankSummary
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    PlayerShortcutDependencies,
    fetch_player_shortcut_reply,
)
from ironsbot.services.seer.rank_models import PlayerRankSummary
from ironsbot.services.seer.sequ_extra import UnityPartOneInfo

PLAYER_ID = 813_824_069


class _Game:
    async def get_user_info(self, player_id: int) -> SimpleNamespace:
        assert player_id == PLAYER_ID
        return SimpleNamespace(nick="decial")

    async def get_more_user_info(self, player_id: int) -> SimpleNamespace:
        assert player_id == PLAYER_ID
        return SimpleNamespace(total_achieve=5760, pet_all_num=1231)


class _Rank:
    async def fetch_player_summary(
        self,
        _game: object,
        player_id: int,
        **kwargs: Any,
    ) -> object:
        assert player_id == PLAYER_ID
        kwargs["progress"].current_title = "皮肤图鉴榜"
        await asyncio.Event().wait()
        raise AssertionError


class _LocalRank:
    config = SimpleNamespace(enabled=False)

    async def upsert_metrics(self, **_kwargs: object) -> LocalRankSummary:
        raise AssertionError


class _RecordingLocalRank:
    config = SimpleNamespace(enabled=True)

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def upsert_metrics(self, **kwargs: object) -> LocalRankSummary:
        self.calls.append(kwargs)
        return LocalRankSummary()


class _RankWithoutData:
    async def fetch_player_summary(
        self,
        _game: object,
        player_id: int,
        **_kwargs: object,
    ) -> PlayerRankSummary:
        assert player_id == PLAYER_ID
        return PlayerRankSummary.empty()


@pytest.mark.asyncio
async def test_collection_returns_partial_result_with_exact_timeout_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch_unity_part_one(
        _game: object,
        player_id: int,
    ) -> UnityPartOneInfo:
        assert player_id == PLAYER_ID
        return UnityPartOneInfo(
            achievement_num=372,
            pet_kind_num=1326,
            skin_num=79,
        )

    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcuts.fetch_unity_part_one",
        fetch_unity_part_one,
    )
    reply = await fetch_player_shortcut_reply(
        PlayerShortcutDependencies(
            rank=cast("Any", _Rank()),
            local_rank=cast("Any", _LocalRank()),
            timeout_seconds=0.01,
        ),
        _Game(),
        command=PlayerShortcutCommand(kind="collection", player_id=PLAYER_ID),
        player_id=PLAYER_ID,
    )

    assert "📚【收集与排行】" in reply.text
    assert reply.text.splitlines()[1].startswith("获取时间：")
    assert f"米米号：{PLAYER_ID}（decial）" in reply.text
    assert "精灵数量：1231" in reply.text
    assert "皮肤图鉴：79｜全服排行失败：查询超时" in reply.text
    assert "❌ 米米号" not in reply.text


@pytest.mark.asyncio
async def test_successful_collection_shortcut_adds_player_to_local_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fetch_unity_part_one(
        _game: object,
        player_id: int,
    ) -> UnityPartOneInfo:
        assert player_id == PLAYER_ID
        return UnityPartOneInfo(
            achievement_num=372,
            pet_kind_num=1326,
            skin_num=79,
        )

    monkeypatch.setattr(
        "ironsbot.services.seer.player_shortcuts.fetch_unity_part_one",
        fetch_unity_part_one,
    )
    local_rank = _RecordingLocalRank()

    await fetch_player_shortcut_reply(
        PlayerShortcutDependencies(
            rank=cast("Any", _RankWithoutData()),
            local_rank=cast("Any", local_rank),
        ),
        _Game(),
        command=PlayerShortcutCommand(kind="collection", player_id=PLAYER_ID),
        player_id=PLAYER_ID,
    )

    assert len(local_rank.calls) == 1
    call = local_rank.calls[0]
    assert call["player_id"] == PLAYER_ID
    assert call["nick"] == "decial"
    metrics = cast("dict[str, object]", call["current_metrics"])
    assert {"achievement_score", "achievement_count", "pet_total_count"} <= set(metrics)
