from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.config.models.messaging import BotRoutingConfig
from ironsbot.core.messaging import MessageTarget
from ironsbot.core.onebot_references import OneBotReferenceResolver
from ironsbot.integrations.onebot import router as bot_router
from ironsbot.integrations.onebot.router import BotRouter

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@dataclass(frozen=True)
class FakeBot:
    self_id: int


def _routing_config(**overrides: object) -> BotRoutingConfig:
    values: dict[str, object] = {
        "enabled": True,
        "default_bot": "main_bot",
        "bot_aliases": {"main_bot": 111111111, "backup_bot": 222222222},
        "groups": {"group_a": "main_bot", "group_b": "backup_bot"},
        "users": {"owner": "main_bot", "user_a": "backup_bot"},
    }
    values.update(overrides)
    return BotRoutingConfig.model_validate(values)


def _patch_router(
    monkeypatch: MonkeyPatch,
    *,
    config: BotRoutingConfig,
    connected: list[FakeBot],
) -> BotRouter:
    monkeypatch.setattr(bot_router, "Bot", FakeBot)
    monkeypatch.setattr(
        bot_router,
        "get_bots",
        lambda: {str(bot.self_id): bot for bot in connected},
    )
    return BotRouter(
        config,
        OneBotReferenceResolver(
            {"group_a": 987654321, "group_b": 876543210},
            {"owner": 1234567890, "user_a": 2345678901},
        ),
    )


def test_bot_router_routes_groups_and_users_by_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    backup_bot = FakeBot(222222222)
    config = _routing_config()
    router = _patch_router(
        monkeypatch,
        config=config,
        connected=[main_bot, backup_bot],
    )

    assert router.for_target(MessageTarget("group", 987654321)) is main_bot
    assert router.for_target(MessageTarget("group", 876543210)) is backup_bot
    assert router.for_target(MessageTarget("private", 1234567890)) is main_bot
    assert router.for_target(MessageTarget("private", 2345678901)) is backup_bot


def test_bot_router_falls_back_to_default_when_routed_bot_is_offline(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    router = _patch_router(
        monkeypatch,
        config=_routing_config(),
        connected=[main_bot],
    )

    assert router.for_target(MessageTarget("group", 876543210)) is main_bot


def test_bot_router_falls_back_to_any_onebot_when_default_is_offline(
    monkeypatch: MonkeyPatch,
) -> None:
    backup_bot = FakeBot(222222222)
    router = _patch_router(
        monkeypatch,
        config=_routing_config(groups={}),
        connected=[backup_bot],
    )

    assert router.for_target(MessageTarget("group", 987654321)) is backup_bot


def test_bot_router_disabled_uses_connected_bot(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    router = _patch_router(
        monkeypatch,
        config=_routing_config(enabled=False),
        connected=[main_bot],
    )

    assert router.for_target(MessageTarget("group", 987654321)) is main_bot
