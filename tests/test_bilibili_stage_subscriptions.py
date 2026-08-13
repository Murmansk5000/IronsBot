from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.messaging import MessageConfig
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.preferences import (
    bili_all_subscription_key,
    bili_stage_subscription_key,
)
from ironsbot.services.messaging.service import MessagingService
from tests.test_bilibili_category_subscriptions import _service
from tests.test_bilibili_outbound_delivery import (
    PUB_TS,
    _item,
    _RecordingDelivery,
    _targets,
)

UID = 912345678


def test_reminder_access_is_checked_by_public_service(tmp_path: Path) -> None:
    service, conversation = _service(tmp_path)
    owner = ActorRef(Platform.ONEBOT, "90000001")
    features = replace(service.features, superusers=frozenset({owner}))
    messaging = MessagingService(
        MessageConfig(),
        ActivityConfig(),
        service.unsubscribe_store,
        features,
        cast(Any, object()),
        cast(Any, object()),
        _extra_push_options=(service.subscription_options,),
        _subscription_submenu_providers=(service,),
    )
    option = service.subscription_options(conversation)[0]
    assert option.superuser_only
    assert "仅超级管理员" in messaging.toggle_subscription(
        conversation, replace(option, superuser_only=False)
    )
    assert "已退订" in messaging.toggle_subscription(conversation, option, actor=owner)
    assert service.unsubscribe_store.is_unsubscribed(conversation, option.key)


@pytest.mark.asyncio
async def test_reminder_optout_does_not_disable_body_or_images(tmp_path: Path) -> None:
    service, conversation = _service(tmp_path)
    target = _targets(full_groups=(1001,))
    group = target.full_group_conversations[0]
    service.unsubscribe_store.unsubscribe(
        group, bili_all_subscription_key("link"), "bili_push"
    )
    recorder = _RecordingDelivery()
    sender = BilibiliDynamicOutboundSender(
        cast(Any, recorder), service.unsubscribe_store
    )
    await sender.send(_item(), PUB_TS, UID, target)
    assert not any(call["requests"] for call in recorder.link_calls)
    assert recorder.content_calls


def test_migration_is_one_time_and_restoring_gate_keeps_account_state(
    tmp_path: Path,
) -> None:
    service, conversation = _service(tmp_path)
    store = service.unsubscribe_store
    store.unsubscribe(conversation, "bili_push:912345678", "bili_push")
    store.migrate_bilibili_subscriptions({UID})
    assert all(
        store.is_unsubscribed(conversation, bili_stage_subscription_key(UID, stage))
        for stage in ("link", "text", "image")
    )
    key = bili_stage_subscription_key(UID, "text")
    store.restore(conversation, key)
    store.migrate_bilibili_subscriptions({UID})
    assert not store.is_unsubscribed(conversation, key)
