from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.messaging import MessageConfig
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.bilibili.preferences import bili_all_subscription_key
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.messaging.subscriptions import PushSubscriptionOption
from ironsbot.services.portable_messaging_commands import (
    build_portable_messaging_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from tests.test_bilibili_category_subscriptions import _service

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_private_td_owner_can_manage_all_authorized_stages(
    tmp_path: Path, platform: Platform
) -> None:
    service, original = _service(tmp_path)
    actor = ActorRef(platform, "private-owner", account_id="bot-a")
    conversation = ConversationRef(platform, "private", actor.id, account_id="bot-a")
    features = replace(
        service.features, actor_features={actor: frozenset({"bili_push"})}
    )
    rule = service.target_rule(original)
    assert rule is not None
    service = replace(
        service,
        features=features,
        configured_targets=replace(
            service.configured_targets, private_rules={conversation: rule}
        ),
    )
    restricted = PushSubscriptionOption(
        "restricted", "管理通知", "admin_notice", superuser_only=True
    )
    messaging = MessagingService(
        MessageConfig(),
        ActivityConfig(),
        service.unsubscribe_store,
        features,
        cast("Any", object()),
        cast("Any", object()),
        _extra_push_options=(service.subscription_options, lambda _: [restricted]),
        _subscription_submenu_providers=(service,),
    )
    context = MessageInputContext(
        IncomingMessageRef(
            platform=platform,
            actor=actor,
            conversation=conversation,
            message_id="private-request",
            text="td",
        ),
        mentions_bot=False,
    )
    sessions = PortableQuerySessions()
    operations = build_portable_messaging_operations(messaging, sessions)
    root = await operations["messaging.push_subscription"]("td", context)
    assert isinstance(root, OutboundMessage)
    root_text = "".join(p.text for p in root.parts if isinstance(p, TextPart))
    assert "所有B站动态提醒（仅超管可修改）" not in root_text
    changed = await sessions.select("1", context)
    assert isinstance(changed, OutboundMessage)
    assert service.unsubscribe_store.is_unsubscribed(
        conversation, bili_all_subscription_key("link")
    )
    root_options = service.subscription_options(conversation)
    submenu = service.subscription_submenu(
        conversation, root_options[-1], read_only=False
    )
    assert submenu is not None
    assert "仅超管" not in submenu[1]
    for option in (*root_options[:3], *submenu[0]):
        result = messaging.toggle_subscription(conversation, option, actor=actor)
        assert result.startswith(("已退订：", "已恢复订阅："))
    stranger = replace(actor, id="another-user")
    assert "自己的私聊" in messaging.toggle_subscription(
        conversation, root_options[0], actor=stranger
    )
    assert "权限" in messaging.toggle_subscription(
        conversation, restricted, actor=actor
    )
    allowed_features = replace(
        features, actor_features={actor: frozenset({"bili_push", "admin_notice"})}
    )
    authorized = replace(messaging, _features=allowed_features)
    assert "仅超级管理员" in authorized.toggle_subscription(
        conversation, restricted, actor=actor
    )
    blocked = replace(
        messaging,
        _features=replace(features, actor_features={actor: frozenset({"blacklist"})}),
    )
    assert "权限" in blocked.toggle_subscription(
        conversation, root_options[0], actor=actor
    )
    revoked = replace(messaging, _features=replace(features, actor_features={}))
    assert "权限" in revoked.toggle_subscription(
        conversation, root_options[0], actor=actor
    )
