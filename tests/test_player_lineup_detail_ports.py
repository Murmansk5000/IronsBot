from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.extensions.player_lineup import PlayerLineupQueryServices
from ironsbot.integrations.seer_data.player_lineup_details import (
    PublishedPlayerLineupDetailResolver,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("failed", [False, True])
async def test_detail_packet_uses_guarded_client_and_defers_quota(
    platform: Platform,
    *,
    failed: bool,
) -> None:
    player = 600001
    game = SimpleNamespace(
        user_id=player,
        get_user_info=AsyncMock(return_value=SimpleNamespace(nick="测试玩家")),
        send_and_wait=AsyncMock(return_value=(None, b"verified")),
        operations=SimpleNamespace(track=lambda *_args, **_kwargs: nullcontext()),
    )
    quotas = Mock(
        check=Mock(return_value=SimpleNamespace(allowed=True)),
        consume=Mock(return_value=SimpleNamespace(allowed=True)),
    )

    async def fetch(client: Any, player_id: int, *, timeout_seconds: float) -> bytes:
        if failed:
            raise TimeoutError
        return await client.request(
            2325, player_id, 200001, timeout_seconds=timeout_seconds
        )

    actor = ActorRef(platform, "actor")
    conversation = ConversationRef(platform, "private", "actor")
    service = PlayerLineupQueryServices(
        headless=cast(
            "Any", SimpleNamespace(get_game=lambda: game, mark_available=AsyncMock())
        ),
        error_message=lambda _code: None,
        quotas=quotas,
    )
    result = await service.query(
        player_id=player,
        actor=actor,
        conversation=conversation,
        timeout_seconds=1,
        fetch_packet=fetch,
        defer_quota=True,
        label="阵容详情",
    )
    quotas.consume.assert_not_called()
    if failed:
        assert result.error and result.record_success is None
        return
    assert result.payload == b"verified"
    assert "【阵容详情】" in result.leading_text
    game.send_and_wait.assert_awaited_once_with(2325, player, 200001, timeout=1)
    assert result.record_success is not None
    result.record_success()
    result.record_success()
    quotas.consume.assert_called_once_with(
        actor=actor, player_id=player, action_key="lineup"
    )


def test_detail_catalog_returns_detached_values_and_skips_unused_queries() -> None:
    skill = SimpleNamespace(id=1001, name="测试技能")
    mintmark = SimpleNamespace(id=42001, name="测试刻印")
    effect = SimpleNamespace(eid=3, effect_args=[10, 0])
    trait = SimpleNamespace(
        effect_in_use=effect, name="测试特性", desc="测试说明", star_level=5
    )
    session = Mock(exec=Mock(side_effect=[(skill,), (mintmark,), (trait,)]))
    data = SimpleNamespace(query=lambda operation: nullcontext(operation(session)))
    resolver = PublishedPlayerLineupDetailResolver(cast("Any", data))
    catalog = resolver.resolve(
        skill_ids=(1001,), mintmark_ids=(42001,), effect_ids=(3,)
    )
    skill.name = "changed"
    effect.effect_args[0] = 99
    assert catalog.skill_names == ((1001, "测试技能"),)
    assert catalog.mintmark_names == ((42001, "测试刻印"),)
    assert catalog.traits[0].args == (10, 0)
    session.exec.reset_mock()
    assert not resolver.resolve(skill_ids=(), mintmark_ids=(), effect_ids=()).traits
    session.exec.assert_not_called()
