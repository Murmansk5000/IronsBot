from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.messaging import MessageConfig
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, SendResult, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.bilibili.live_preview import LIVE_ALL_SUBSCRIPTION, SEER_LIVE_UID
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.portable_messaging_commands import (
    build_portable_messaging_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from tests.test_bilibili_category_subscriptions import _service


@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
def test_live_options_use_current_conversation_policy_and_persist(
    tmp_path: Path, platform: Platform
) -> None:
    service, original = _service(tmp_path)
    target = ConversationRef(
        platform, "group", "synthetic-group", account_id="test-bot"
    )
    actor = ActorRef(platform, "operator", account_id="test-bot")
    manager = replace(actor, id="manager")
    rule = service.target_rule(original)
    assert rule is not None
    service.linked_group_rules[target] = rule
    features = replace(
        service.features,
        group_features={target: frozenset({"bili_push"})},
        superusers=frozenset({actor}),
    )
    service = replace(service, features=features)
    messaging = MessagingService(
        MessageConfig(),
        ActivityConfig(),
        service.unsubscribe_store,
        features,
        cast("Any", object()),
        cast("Any", object()),
        _extra_push_options=(service.subscription_options,),
        _subscription_submenu_providers=(service,),
    )
    root = service.subscription_options(target)
    submenu = service.subscription_submenu(target, root[-1], read_only=False)
    assert submenu is not None
    live = next(option for option in submenu[0] if option.label == "直播提醒")
    assert live.unsubscribed
    assert not live.group_superuser_only
    forged = replace(live, group_superuser_only=True)
    assert "恢复订阅" in messaging.toggle_subscription(target, forged, actor=manager)
    assert service.live_enabled(target, 912345678)
    total = next(option for option in root if option.key == LIVE_ALL_SUBSCRIPTION)
    assert not total.group_superuser_only
    assert "已退订" in messaging.toggle_subscription(target, total, actor=manager)
    assert not service.live_enabled(target, 912345678)
    assert service.live_enabled(target, 912345678, include_global=False)
    assert "恢复订阅" in messaging.toggle_subscription(target, total, actor=actor)
    reopened, _ = _service(tmp_path)
    assert (
        reopened.live_enabled(original, 912345678) is False
    )  # Other bot/session stays isolated.
    assert service.live_enabled(target, 912345678)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("role", ["owner", "admin", "member", "superuser"])
@pytest.mark.parametrize("account_switch", [False, True])
async def test_live_switch_permissions_on_public_td_entry(
    tmp_path: Path, platform: Platform, role: str, *, account_switch: bool
) -> None:
    service, original = _service(tmp_path)
    target = ConversationRef(platform, "group", "synthetic-group", account_id="bot")
    actor = ActorRef(platform, "operator", account_id="bot")
    rule = service.target_rule(original)
    assert rule is not None
    service.linked_group_rules[target] = rule
    features = replace(
        service.features,
        group_features={target: frozenset({"bili_push"})},
        superusers=frozenset({actor}) if role == "superuser" else frozenset(),
    )
    service = replace(service, features=features)
    messaging = MessagingService(
        MessageConfig(),
        ActivityConfig(),
        service.unsubscribe_store,
        features,
        cast("Any", object()),
        cast("Any", object()),
        _extra_push_options=(service.subscription_options,),
        _subscription_submenu_providers=(service,),
    )
    context = MessageInputContext(
        IncomingMessageRef(
            platform=platform,
            actor=actor,
            conversation=target,
            message_id="request",
            text="td",
            group_role="member" if role == "superuser" else role,
        ),
        mentions_bot=True,
    )
    sessions = PortableQuerySessions()
    operation = build_portable_messaging_operations(messaging, sessions)[
        "messaging.push_subscription"
    ]
    root = await operation("td", context)
    assert isinstance(root, OutboundMessage)
    sessions.record_delivery(
        context, root, SendResult(delivered=True, message_id="root")
    )
    options = service.subscription_options(target)
    if account_switch:
        child = await sessions.select(str(len(options)), context)
        assert isinstance(child, OutboundMessage)
        sessions.record_delivery(
            context, child, SendResult(delivered=True, message_id="child")
        )
        submenu = service.subscription_submenu(target, options[-1], read_only=False)
        assert submenu is not None
        options = submenu[0]
    key = "bili_live:912345678" if account_switch else LIVE_ALL_SUBSCRIPTION
    index = next(i for i, option in enumerate(options, 1) if option.key == key)
    before = service.live_enabled(target, 912345678, include_global=False)
    result = await sessions.select(str(index), context)
    assert isinstance(result, OutboundMessage)
    text = "".join(part.text for part in result.parts if isinstance(part, TextPart))
    if role == "member":
        assert "普通群成员只能查看" in text
        assert service.live_enabled(target, 912345678, include_global=False) == before
        assert not service.unsubscribe_store.is_unsubscribed(target, key)
        return
    assert "仅超管可修改）" not in next(
        line for line in text.splitlines() if "直播提醒" in line
    )
    assert "已恢复订阅" in text if account_switch else "已退订" in text
    sessions.record_delivery(
        context, result, SendResult(delivered=True, message_id="changed")
    )
    if role != "superuser":
        downgraded = replace(
            context, message=replace(context.message, group_role="member")
        )
        denied = await sessions.select(str(index), downgraded)
        assert isinstance(denied, OutboundMessage)
        assert "普通群成员只能查看" in "".join(
            part.text for part in denied.parts if isinstance(part, TextPart)
        )
        assert (
            service.live_enabled(target, 912345678, include_global=False)
            == account_switch
        )


def test_default_seer_and_preview_veto_are_independent(tmp_path: Path) -> None:
    service, target = _service(tmp_path)
    rule = service.target_rule(target)
    assert rule is not None
    service = replace(
        service,
        configured_targets=replace(
            service.configured_targets,
            group_rules={target: replace(rule, uids=rule.uids | {SEER_LIVE_UID})},
        ),
    )
    assert service.live_enabled(target, SEER_LIVE_UID)
    assert not service.live_enabled(target, 912345678)
    root = service.subscription_options(target)
    ordinary = next(option for option in root if "912345678" in option.key)
    submenu = service.subscription_submenu(target, ordinary, read_only=False)
    assert submenu
    preview = next(option for option in submenu[0] if option.label == "直播预告")
    result = service.toggle_subscription(target, preview)
    assert result is not None and "退订" in result
    assert not service.push_targets_for_dynamic(
        912345678, categories=("live_preview", "news")
    ).has_targets
    assert not service.live_enabled(target, 912345678)
    assert service.live_enabled(target, SEER_LIVE_UID)
