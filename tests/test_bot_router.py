from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.config.models.messaging import BotRoutingConfig
from ironsbot.config.onebot_references import OneBotReferenceResolver
from ironsbot.core.platform import ConversationRef, Platform, reference_digest
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
    use_default_for_unconfigured_groups: bool = False,
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
        use_default_for_unconfigured_groups,
    )


def _group(group_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _private(user_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "private", str(user_id))


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

    assert router.for_conversation(_group(987654321)) is main_bot
    assert router.for_conversation(_group(876543210)) is backup_bot
    assert router.for_conversation(_private(1234567890)) is main_bot
    assert router.for_conversation(_private(2345678901)) is backup_bot


def test_bot_router_does_not_fall_back_when_routed_bot_is_offline(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    router = _patch_router(
        monkeypatch,
        config=_routing_config(),
        connected=[main_bot],
    )

    assert router.for_conversation(_group(876543210)) is None


def test_bot_router_rejects_delivery_when_default_is_offline(
    monkeypatch: MonkeyPatch,
) -> None:
    backup_bot = FakeBot(222222222)
    router = _patch_router(
        monkeypatch,
        config=_routing_config(groups={}),
        connected=[backup_bot],
    )

    assert router.for_conversation(_group(987654321)) is None


def test_bot_router_uses_default_for_unconfigured_group_when_enabled(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    router = _patch_router(
        monkeypatch,
        config=_routing_config(enabled=False),
        connected=[main_bot],
        use_default_for_unconfigured_groups=True,
    )

    assert router.for_conversation(_group(987654321)) is main_bot


def test_bot_router_disabled_without_default_bot_rejects_delivery(
    monkeypatch: MonkeyPatch,
) -> None:
    backup_bot = FakeBot(222222222)
    router = _patch_router(
        monkeypatch,
        config=_routing_config(enabled=False, default_bot=None),
        connected=[backup_bot],
    )

    assert router.default_bot() is None
    assert router.for_conversation(_group(987654321)) is None


def test_bot_router_unavailable_logs_use_identity_digests(
    monkeypatch: MonkeyPatch,
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        bot_router.logger,
        "warning",
        lambda message, *args: messages.append(message.format(*args)),
    )
    router = _patch_router(
        monkeypatch,
        config=_routing_config(groups={}),
        connected=[],
        use_default_for_unconfigured_groups=True,
    )

    assert router.for_conversation(_group(987654321)) is None

    rendered = "\n".join(messages)
    assert "987654321" not in rendered
    assert "111111111" not in rendered
    assert reference_digest("987654321") in rendered
    assert reference_digest("111111111") in rendered


def test_bot_router_ignores_unconfigured_group_by_default(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    router = _patch_router(
        monkeypatch,
        config=_routing_config(groups={}),
        connected=[main_bot],
    )

    conversation = _group(987654321)
    assert router.for_conversation(conversation) is None
    assert not router.allows_incoming(main_bot.self_id, conversation)
    assert not router.allows_outbound(conversation)


def test_bot_router_default_owns_unconfigured_group_when_enabled(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    backup_bot = FakeBot(222222222)
    router = _patch_router(
        monkeypatch,
        config=_routing_config(groups={}),
        connected=[main_bot, backup_bot],
        use_default_for_unconfigured_groups=True,
    )

    conversation = _group(987654321)
    assert router.for_conversation(conversation) is main_bot
    assert router.allows_incoming(main_bot.self_id, conversation)
    assert not router.allows_incoming(backup_bot.self_id, conversation)
    assert router.allows_outbound(conversation)
