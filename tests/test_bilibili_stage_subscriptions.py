from __future__ import annotations

import itertools
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.messaging import MessageConfig
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import (
    DeliveryFailureKind,
    OutboundMessage,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.bilibili.delivery_recovery import BiliDeliveryRecovery
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.preferences import (
    BILI_STAGE_LABELS,
    bili_all_subscription_key,
    bili_media_subscription_key,
    bili_push_subscription_key,
)
from ironsbot.services.bilibili.target_models import BiliPushTargets
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.portable_messaging_commands import (
    build_portable_messaging_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from tests.test_bilibili_category_subscriptions import _service
from tests.test_bilibili_outbound_delivery import _item, _RecordingDelivery

UID = 912345678

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
def test_reminder_mutation_checks_live_constraint_and_actual_actor(
    tmp_path: Path, platform: Platform
) -> None:
    service, original = _service(tmp_path, categories=False)
    conversation = ConversationRef(platform, "group", "group-a", account_id="bot-a")
    actor = ActorRef(platform, "owner", account_id="bot-a")
    manager = ActorRef(platform, "manager", account_id="bot-a")
    rule = service.target_rule(original)
    assert rule is not None
    service.linked_group_rules[conversation] = rule
    features = replace(
        service.features,
        group_features={conversation: frozenset({"bili_push"})},
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
    root = service.subscription_options(conversation)
    submenu = service.subscription_submenu(conversation, root[-1], read_only=False)
    assert submenu is not None
    for option in (root[0], submenu[0][0]):
        forged = replace(option, superuser_only=False, group_superuser_only=False)
        assert "仅超级管理员" in messaging.toggle_subscription(
            conversation, forged, actor=manager
        )
        assert not service.unsubscribe_store.is_unsubscribed(conversation, option.key)
        assert "已退订" in messaging.toggle_subscription(
            conversation, forged, actor=actor
        )
        assert service.unsubscribe_store.is_unsubscribed(conversation, option.key)
    # A stale menu cannot retain superuser privileges after a policy change.
    messaging = replace(messaging, _features=replace(features, superusers=frozenset()))
    assert "仅超级管理员" in messaging.toggle_subscription(
        conversation, root[0], actor=actor
    )
    assert "已退订" in messaging.toggle_subscription(
        conversation, root[1], actor=manager
    )
    assert "已退订" in messaging.toggle_subscription(
        conversation, submenu[0][1], actor=manager
    )


def test_legacy_migration_preserves_effective_state_and_is_idempotent(
    tmp_path: Path,
) -> None:
    store = PushUnsubscribeStore(tmp_path / "state.sqlite")
    conversation = ConversationRef(Platform.ONEBOT, "group", "100")
    category_uid = 1310714247
    store.unsubscribe(conversation, bili_push_subscription_key(UID), "bili_push")
    store.unsubscribe(
        conversation, bili_media_subscription_key(UID, "image"), "bili_push"
    )
    store.unsubscribe(
        conversation, bili_media_subscription_key(UID + 1, "text"), "bili_push"
    )
    store.unsubscribe(
        conversation, bili_media_subscription_key(category_uid, "image"), "bili_push"
    )
    store.migrate_bilibili_subscriptions({category_uid})
    assert bili_push_subscription_key(UID) not in store.unsubscribed_keys(conversation)
    assert all(
        store.is_unsubscribed(conversation, bili_media_subscription_key(UID, stage))
        for stage in BILI_STAGE_LABELS
    )
    assert not store.is_unsubscribed(
        conversation, bili_media_subscription_key(UID + 1, "text")
    )
    assert store.is_unsubscribed(
        conversation, bili_media_subscription_key(category_uid, "image")
    )
    store.restore(conversation, bili_media_subscription_key(UID, "text"))
    restarted = PushUnsubscribeStore(store.path)
    restarted.migrate_bilibili_subscriptions(set())
    assert not restarted.is_unsubscribed(
        conversation, bili_media_subscription_key(UID, "text")
    )
    assert restarted.is_unsubscribed(
        conversation, bili_media_subscription_key(category_uid, "image")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", list(itertools.product((False, True), repeat=3)))
@pytest.mark.parametrize("mode", ["full", "link"])
async def test_all_stages_are_independent_and_link_mode_does_not_expand(
    tmp_path: Path, enabled: tuple[bool, bool, bool], mode: str
) -> None:
    store = PushUnsubscribeStore(tmp_path / "state.sqlite")
    target = ConversationRef(Platform.ONEBOT, "group", "100")
    for stage, allowed in zip(BILI_STAGE_LABELS, enabled, strict=True):
        if not allowed:
            store.unsubscribe(
                target, bili_media_subscription_key(UID, stage), "bili_push"
            )
    delivery = _RecordingDelivery()
    sender = BilibiliDynamicOutboundSender(cast("Any", delivery), store)
    targets = BiliPushTargets(
        [target] if mode == "full" else [], [target] if mode == "link" else [], [], []
    )
    await sender.send(_item(), int(time.time()), UID, targets)
    assert bool(delivery.link_calls) == enabled[0]
    assert len(delivery.content_calls) == (sum(enabled[1:]) if mode == "full" else 0)


@pytest.mark.asyncio
async def test_global_gate_does_not_overwrite_accounts_or_other_conversations(
    tmp_path: Path,
) -> None:
    store = PushUnsubscribeStore(tmp_path / "state.sqlite")
    a = ConversationRef(Platform.ONEBOT, "group", "100")
    b = ConversationRef(Platform.ONEBOT, "group", "200")
    store.unsubscribe(a, bili_media_subscription_key(UID, "text"), "bili_push")
    store.unsubscribe(a, bili_all_subscription_key("text"), "bili_push")
    for uid in (UID, UID + 1):
        delivery = _RecordingDelivery()
        await BilibiliDynamicOutboundSender(cast("Any", delivery), store).send(
            _item(include_image=False),
            int(time.time()),
            uid,
            BiliPushTargets([a, b], [], [], []),
        )
        assert [call["conversations"] for call in delivery.content_calls] == [(b,)]
    store.restore(a, bili_all_subscription_key("text"))
    delivery = _RecordingDelivery()
    await BilibiliDynamicOutboundSender(cast("Any", delivery), store).send(
        _item(include_image=False),
        int(time.time()),
        UID + 1,
        BiliPushTargets([a], [], [], []),
    )
    assert delivery.content_calls
    assert store.is_unsubscribed(a, bili_media_subscription_key(UID, "text"))


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_td_submenu_back_and_reminder_permission_on_public_entry(
    tmp_path: Path, platform: Platform
) -> None:
    service, original = _service(tmp_path, categories=False)
    target = ConversationRef(platform, "group", "456", account_id="bot")
    rule = service.target_rule(original)
    assert rule is not None
    service.linked_group_rules[target] = rule
    service = replace(
        service,
        features=replace(
            service.features, group_features={target: frozenset({"bili_push"})}
        ),
    )
    actor = ActorRef(platform, "101", account_id="bot")
    context = MessageInputContext(
        IncomingMessageRef(
            platform=platform,
            actor=actor,
            conversation=target,
            message_id="request",
            text="td",
            group_role="admin",
        ),
        mentions_bot=True,
    )
    messaging = MessagingService(
        MessageConfig(),
        ActivityConfig(),
        service.unsubscribe_store,
        service.features,
        cast("Any", object()),
        cast("Any", object()),
        _extra_push_options=(service.subscription_options,),
        _subscription_submenu_providers=(service,),
    )
    sessions = PortableQuerySessions()
    operations = build_portable_messaging_operations(messaging, sessions)
    root = await operations["messaging.push_subscription"]("td", context)
    assert isinstance(root, OutboundMessage)
    sessions.record_delivery(
        context, root, SendResult(delivered=True, message_id="root")
    )
    child = await sessions.select("4", context)
    assert isinstance(child, OutboundMessage)
    sessions.record_delivery(
        context, child, SendResult(delivered=True, message_id="child")
    )
    rejected = await sessions.select("1", context)
    assert isinstance(rejected, OutboundMessage)
    assert "仅超级管理员" in "".join(
        part.text for part in rejected.parts if isinstance(part, TextPart)
    )
    sessions.record_delivery(
        context, rejected, SendResult(delivered=True, message_id="rejected")
    )
    back = await sessions.select("0", context)
    assert isinstance(back, OutboundMessage)
    assert "所有B站动态正文" in "".join(
        part.text for part in back.parts if isinstance(part, TextPart)
    )


@pytest.mark.asyncio
async def test_recovery_skips_disabled_link_and_never_replays_it_after_reenable(
    tmp_path: Path,
) -> None:
    store = PushUnsubscribeStore(tmp_path / "state.sqlite")
    target = ConversationRef(Platform.ONEBOT, "group", "100")
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    item = _item()
    dynamic_id = str(item["id_str"])
    targets = BiliPushTargets([], [target], [], [])
    ledger.prepare(item, int(time.time()), UID, targets, ())
    store.unsubscribe(target, bili_all_subscription_key("link"), "bili_push")
    delivery = _RecordingDelivery()
    sender = BilibiliDynamicOutboundSender(cast("Any", delivery), store, ledger=ledger)
    await sender.send(item, int(time.time()), UID, targets, resume=True)
    assert not delivery.link_calls
    assert ledger.state_counts(dynamic_id).get("skipped") == 1
    store.restore(target, bili_all_subscription_key("link"))
    await sender.send(item, int(time.time()), UID, targets, resume=True)
    assert not delivery.link_calls


@pytest.mark.asyncio
async def test_disabled_media_is_not_prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PushUnsubscribeStore(tmp_path / "state.sqlite")
    target = ConversationRef(Platform.ONEBOT, "group", "100")
    for stage in BILI_STAGE_LABELS:
        store.unsubscribe(target, bili_all_subscription_key(stage), "bili_push")
    prepare_images = AsyncMock()
    prepare_text = AsyncMock()
    monkeypatch.setattr(
        BilibiliDynamicOutboundSender, "_prepare_frozen_images", prepare_images
    )
    monkeypatch.setattr(
        BilibiliDynamicOutboundSender, "_prepare_text_message", prepare_text
    )
    delivery = _RecordingDelivery()
    await BilibiliDynamicOutboundSender(cast("Any", delivery), store).send(
        _item(), int(time.time()), UID, BiliPushTargets([target], [], [], [])
    )
    assert not delivery.link_calls and not delivery.content_calls
    prepare_images.assert_not_awaited()
    prepare_text.assert_not_awaited()


def test_skip_keeps_successful_and_uncertain_receipts(tmp_path: Path) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    target = ConversationRef(Platform.ONEBOT, "group", "100")
    item = _item()
    ident = str(item["id_str"])
    ledger.prepare(
        item, int(time.time()), UID, BiliPushTargets([target], [], [], []), ()
    )
    assert ledger.claim(ident, target, "link")
    ledger.finish(ident, target, "link", SendResult(delivered=True, message_id="sent"))
    assert ledger.claim(ident, target, "text")
    ledger.finish(
        ident,
        target,
        "text",
        SendResult(
            delivered=False,
            error_code="receipt_timeout",
            failure_kind=DeliveryFailureKind.UNCERTAIN,
        ),
    )
    before = ledger.state_counts(ident)
    ledger.skip_stage(ident, target, "link")
    ledger.skip_stage(ident, target, "text")
    assert ledger.state_counts(ident) == before
    assert not ledger.unattempted(ident, target, "text")


@pytest.mark.asyncio
async def test_recovery_never_promotes_original_link_target_to_content(
    tmp_path: Path,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    target = ConversationRef(Platform.ONEBOT, "group", "100")
    item = _item()
    ledger.prepare(
        item, int(time.time()), UID, BiliPushTargets([], [target], [], []), ()
    )
    sender = Mock(ledger=ledger, send=AsyncMock())
    targets = Mock()
    targets.push_targets_for_dynamic.return_value = BiliPushTargets(
        [target], [], [], []
    )
    recovery = BiliDeliveryRecovery(cast("Any", sender), cast("Any", targets))
    await recovery()
    selected = sender.send.await_args.args[3]
    assert selected.link_group_conversations == [target]
    assert not selected.full_group_conversations


@pytest.mark.asyncio
async def test_recovery_terminally_skips_targets_removed_by_policy(
    tmp_path: Path,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    target = ConversationRef(Platform.ONEBOT, "group", "100")
    item = _item()
    ident = str(item["id_str"])
    ledger.prepare(
        item, int(time.time()), UID, BiliPushTargets([target], [], [], []), ()
    )
    assert ledger.claim(ident, target, "link")
    ledger.finish(
        ident,
        target,
        "link",
        SendResult(
            delivered=False,
            error_code="offline",
            failure_kind=DeliveryFailureKind.TRANSPORT_UNAVAILABLE,
        ),
    )
    sender = Mock(ledger=ledger, send=AsyncMock())
    targets = Mock()
    targets.push_targets_for_dynamic.return_value = BiliPushTargets([], [], [], [])
    await BiliDeliveryRecovery(cast("Any", sender), cast("Any", targets))()
    sender.send.assert_not_awaited()
    assert not ledger.pending()


def test_child_preference_keys_survive_startup_pruning(tmp_path: Path) -> None:
    service, conversation = _service(tmp_path, categories=False)
    messaging = MessagingService(
        MessageConfig(),
        ActivityConfig(),
        service.unsubscribe_store,
        service.features,
        cast("Any", object()),
        cast("Any", object()),
        _extra_push_options=(service.subscription_options,),
        _subscription_submenu_providers=(service,),
    )
    key = bili_media_subscription_key(UID, "image")
    service.unsubscribe_store.unsubscribe(conversation, key, "bili_push")
    keys = {option.key for option in messaging._all_subscription_options(conversation)}
    service.unsubscribe_store.prune_invalid_preferences(
        valid_unsubscription_keys={conversation: keys}, valid_time_preferences={}
    )
    assert service.unsubscribe_store.is_unsubscribed(conversation, key)
