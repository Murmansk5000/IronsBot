from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.runtime import BotRoutingConfig
from ironsbot.shared.messaging import bot_router
from ironsbot.shared.messaging.targets import MessageTarget
from tests.helpers.config import stub_app_config

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
    legacy_default: FakeBot | None = None,
) -> None:
    app_config = stub_app_config(
        feature_config=FeatureConfig(
            group_aliases={"group_a": 987654321, "group_b": 876543210},
            user_aliases={"owner": 1234567890, "user_a": 2345678901},
        ),
        bot_routing_config=config,
    )
    monkeypatch.setattr(bot_router, "get_app_config", lambda: app_config)
    monkeypatch.setattr(bot_router, "Bot", FakeBot)
    monkeypatch.setattr(
        bot_router,
        "get_bots",
        lambda: {str(bot.self_id): bot for bot in connected},
    )
    monkeypatch.setattr(bot_router, "get_bot", lambda: legacy_default)


def test_bot_router_routes_groups_and_users_by_alias(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    backup_bot = FakeBot(222222222)
    config = _routing_config()
    _patch_router(
        monkeypatch,
        config=config,
        connected=[main_bot, backup_bot],
    )

    assert bot_router.resolve_bot_id("backup_bot") == backup_bot.self_id
    assert bot_router.resolve_bot_id(111111111) == main_bot.self_id
    assert bot_router.get_bot_for_group(987654321) is main_bot
    assert bot_router.get_bot_for_group(876543210) is backup_bot
    assert bot_router.get_bot_for_user(1234567890) is main_bot
    assert bot_router.get_bot_for_user(2345678901) is backup_bot


def test_bot_router_falls_back_to_default_when_routed_bot_is_offline(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    _patch_router(
        monkeypatch,
        config=_routing_config(),
        connected=[main_bot],
    )

    assert bot_router.get_bot_for_group(876543210) is main_bot


def test_bot_router_falls_back_to_any_onebot_when_default_is_offline(
    monkeypatch: MonkeyPatch,
) -> None:
    backup_bot = FakeBot(222222222)
    _patch_router(
        monkeypatch,
        config=_routing_config(groups={}),
        connected=[backup_bot],
    )

    assert bot_router.get_bot_for_group(987654321) is backup_bot


def test_bot_router_disabled_uses_legacy_default_bot(
    monkeypatch: MonkeyPatch,
) -> None:
    main_bot = FakeBot(111111111)
    backup_bot = FakeBot(222222222)
    _patch_router(
        monkeypatch,
        config=_routing_config(enabled=False),
        connected=[main_bot, backup_bot],
        legacy_default=backup_bot,
    )

    assert (
        bot_router.get_bot_for_target(MessageTarget("group", 987654321))
        is backup_bot
    )
