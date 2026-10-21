from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from ironsbot.config.models.transport import OneBotRoutingConfig
from ironsbot.config.qq_references import QQReferenceError, QQReferenceResolver
from ironsbot.core.platform import ConversationRef, Platform, reference_digest
from ironsbot.integrations.onebot import router as bot_router
from ironsbot.integrations.onebot.router import BotRouter
from ironsbot.services.onebot_routing import OneBotRoutingPolicy

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@dataclass(frozen=True)
class FakeBot:
    self_id: int


def _routing_config(**overrides: object) -> OneBotRoutingConfig:
    values: dict[str, object] = {
        "enabled": True,
        "default_bot": "main_bot",
        "bot_aliases": {"main_bot": 111111111, "backup_bot": 222222222},
        "groups": {"group_a": "main_bot", "group_b": "backup_bot"},
        "users": {"owner": "main_bot", "user_a": "backup_bot"},
    }
    values.update(overrides)
    return OneBotRoutingConfig.model_validate(values)


def _patch_router(
    monkeypatch: MonkeyPatch,
    *,
    config: OneBotRoutingConfig,
    connected: list[FakeBot],
    use_default_for_unconfigured_targets: bool = False,
) -> BotRouter:
    monkeypatch.setattr(bot_router, "Bot", FakeBot)
    monkeypatch.setattr(
        bot_router,
        "get_bots",
        lambda: {str(bot.self_id): bot for bot in connected},
    )
    return BotRouter(
        OneBotRoutingPolicy(
            config,
            QQReferenceResolver(
                {"group_a": 987654321, "group_b": 876543210},
                {"owner": 1234567890, "user_a": 2345678901},
            ),
            use_default_for_unconfigured_targets,
        ),
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


def test_unconfigured_private_push_skips_but_incoming_query_is_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    router = _patch_router(
        monkeypatch, config=_routing_config(users={}), connected=[main_bot]
    )
    target = _private(3456789012)
    assert router.policy.push_route(target).status == "skipped"
    assert not router.policy.allows_outbound(target)
    assert router.for_conversation(target) is None
    assert router.policy.allows_incoming(main_bot.self_id, target)


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
        use_default_for_unconfigured_targets=True,
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
        use_default_for_unconfigured_targets=True,
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
    assert not router.policy.allows_incoming(main_bot.self_id, conversation)
    assert not router.policy.allows_outbound(conversation)


def test_bot_router_default_owns_unconfigured_group_when_enabled(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    backup_bot = FakeBot(222222222)
    router = _patch_router(
        monkeypatch,
        config=_routing_config(groups={}),
        connected=[main_bot, backup_bot],
        use_default_for_unconfigured_targets=True,
    )

    conversation = _group(987654321)
    assert router.for_conversation(conversation) is main_bot
    assert router.policy.allows_incoming(main_bot.self_id, conversation)
    assert not router.policy.allows_incoming(backup_bot.self_id, conversation)
    assert router.policy.allows_outbound(conversation)


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("routes_enabled", [False, True])
@pytest.mark.parametrize("use_default", [False, True])
def test_shared_routing_matrix_does_not_access_connection_registry(
    monkeypatch: MonkeyPatch,
    *,
    private: bool,
    configured: bool,
    routes_enabled: bool,
    use_default: bool,
) -> None:
    def forbidden_lookup() -> None:
        pytest.fail("shared routing must not access NoneBot connections")

    monkeypatch.setattr(bot_router, "get_bots", forbidden_lookup)
    main = 111111111
    configured_bot = 222222222
    config = _routing_config(
        enabled=routes_enabled,
        groups={"target": "backup_bot"} if configured else {},
        users={"target": "backup_bot"} if configured else {},
    )
    policy = OneBotRoutingPolicy(
        config,
        QQReferenceResolver({"target": 987654321}, {"target": 987654321}),
        use_default,
    )
    target = _private(987654321) if private else _group(987654321)
    selected = (
        configured_bot
        if configured and routes_enabled
        else main
        if use_default
        else None
    )
    decision = policy.resolve(target)
    assert decision.bot_id == selected
    assert policy.allows_outbound(target) is (selected is not None)
    assert policy.push_route(target).status == (
        "ready" if selected is not None else "skipped"
    )
    assert policy.allows_incoming(main, target) is (private or selected == main)
    assert policy.allows_incoming(configured_bot, target) is (
        private or selected == configured_bot
    )


def test_missing_default_account_is_unavailable_not_an_implicit_selection() -> None:
    policy = OneBotRoutingPolicy(
        _routing_config(default_bot=None, groups={}, users={}),
        QQReferenceResolver({}, {}),
        use_default_for_unconfigured_targets=True,
    )
    target = _group(987654321)
    assert policy.resolve(target).bot_id is None
    assert policy.push_route(target).status == "unavailable"
    assert policy.push_route(target).reason == "missing_default_bot"


@pytest.mark.parametrize(
    "target",
    [
        ConversationRef(Platform.QQ_OFFICIAL, "group", "opaque", account_id="app"),
        _group(-1),
        _private(0),
    ],
)
def test_policy_rejects_invalid_outbound_targets(target: ConversationRef) -> None:
    policy = OneBotRoutingPolicy(
        _routing_config(),
        QQReferenceResolver({}, {}),
        use_default_for_unconfigured_targets=True,
    )
    assert not policy.allows_outbound(target)
    assert policy.resolve(target).reason == "invalid_target"
    assert policy.push_route(target).status == "skipped"


def test_account_display_name_uses_the_same_authoritative_configuration() -> None:
    policy = OneBotRoutingPolicy(_routing_config(), QQReferenceResolver({}, {}))
    assert policy.account_name("111111111") == "main_bot"
    assert policy.account_name("333333333") == "333333333"


def test_connection_lookup_error_does_not_expose_source_exception(
    monkeypatch: MonkeyPatch,
) -> None:
    messages: list[str] = []

    def unavailable() -> None:
        raise RuntimeError("private-registry-detail")

    monkeypatch.setattr(bot_router, "get_bots", unavailable)
    monkeypatch.setattr(
        bot_router.logger,
        "warning",
        lambda message, *args: messages.append(message.format(*args)),
    )
    policy = OneBotRoutingPolicy(
        _routing_config(groups={}),
        QQReferenceResolver({}, {}),
        use_default_for_unconfigured_targets=True,
    )
    assert BotRouter(policy).for_conversation(_group(987654321)) is None
    assert "RuntimeError" in "\n".join(messages)
    assert "private-registry-detail" not in "\n".join(messages)


@pytest.mark.parametrize(
    ("section", "target"),
    [
        ("groups", _group(987654321)),
        ("users", _private(987654321)),
    ],
)
def test_route_reference_error_names_the_actual_configuration_section(
    section: str, target: ConversationRef
) -> None:
    policy = OneBotRoutingPolicy(
        _routing_config(**{section: {"unknown": "main_bot"}}),
        QQReferenceResolver({}, {}),
    )
    with pytest.raises(
        QQReferenceError, match=rf"bot\.onebot\.routing\.{section}\.unknown"
    ):
        policy.resolve(target)
