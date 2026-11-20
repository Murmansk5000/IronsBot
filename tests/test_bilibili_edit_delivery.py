from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.outbound import (
    DeliveryCapabilities,
    DeliveryFailureKind,
    OutboundMessage,
    SendResult,
)
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.services.bilibili.delivery_recovery import BiliDeliveryRecovery
from ironsbot.services.bilibili.outbound_delivery import BilibiliDynamicOutboundSender
from ironsbot.services.bilibili.preferences import bili_stage_subscription_key
from ironsbot.services.bilibili.revisions import REVISION_META, delivery_key
from ironsbot.services.bilibili.target_models import BiliPushTargets
from tests.test_bilibili_conversation_queue import drain
from tests.test_bilibili_revisions import UID, item
from tests.test_proactive_delivery import FakeMessenger, _delivery, _text

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class EditRenderer:
    calls: list[str] = field(default_factory=list)
    invisible: bool = False

    async def text(self, _item: dict) -> OutboundMessage:
        self.calls.append("text")
        return OutboundMessage.from_text("TEXT_DIFF")

    async def media(self, _item: dict) -> OutboundMessage | None:
        self.calls.append("image")
        return None if self.invisible else OutboundMessage.from_text("IMAGE_DIFF")


class Messenger(FakeMessenger):
    def capabilities_for(self, conversation: ConversationRef) -> DeliveryCapabilities:
        return replace(
            super().capabilities_for(conversation),
            can_send_proactively=True,
            supports_images=True,
            supports_group_context=True,
            supports_private_context=True,
        )


def edited(*, text: bool = True, media: bool = False, sequence: int = 1) -> dict:
    value = item("after" if text else "before", "new.png" if media else "old.jpg")
    value[REVISION_META] = {
        "key": f"123456:edit:{sequence}",
        "previous_key": "123456",
        "before": item(),
        "text_changed": text,
        "images_changed": media,
        "observed_at": time.time(),
        "published_at": int(time.time()),
        "sequence": sequence,
    }
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("text,media", [(True, False), (False, True), (True, True)])
async def test_edits_send_only_changed_stages_and_resume_once(
    tmp_path: Path, platform: Platform, *, text: bool, media: bool
) -> None:
    messenger, owner, renderer = Messenger(), TaskOwner(), EditRenderer()
    delivery, _, subscriptions = _delivery(messenger=messenger)
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    sender = BilibiliDynamicOutboundSender(
        delivery,
        cast("Any", subscriptions),
        ledger=ledger,
        spawn=owner.create,
        edit_renderer=cast("Any", renderer),
    )
    target = ConversationRef(platform, "group", "test-group", account_id="test-bot")
    data = edited(text=text, media=media)
    targets = BiliPushTargets([target], [], [], [])
    await sender.send(data, int(time.time()), UID, targets)
    await drain(owner)
    messages = [_text(message) for _, message in messenger.calls]
    assert any("动态已修改" in message for message in messages)
    assert any("TEXT_DIFF" in message for message in messages) is text
    assert any("IMAGE_DIFF" in message for message in messages) is media
    before = len(messenger.calls)
    await sender.send(data, int(time.time()), UID, targets, resume=True)
    await drain(owner)
    assert len(messenger.calls) == before
    assert data["id_str"] == "123456"
    assert ledger.stage_state(delivery_key(data), target, "link") == "success"
    assert ledger.stage_state("123456", target, "link") == "skipped"


@pytest.mark.asyncio
async def test_td_body_off_cannot_be_bypassed_by_body_rendered_as_image(
    tmp_path: Path,
) -> None:
    messenger, owner, renderer = Messenger(), TaskOwner(), EditRenderer()
    delivery, _, subscriptions = _delivery(messenger=messenger)
    target = ConversationRef(Platform.ONEBOT, "group", "test-group")
    subscriptions.unsubscribed.add((target, bili_stage_subscription_key(UID, "text")))
    sender = BilibiliDynamicOutboundSender(
        delivery,
        cast("Any", subscriptions),
        ledger=SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite"),
        spawn=owner.create,
        edit_renderer=cast("Any", renderer),
    )
    await sender.send(
        edited(), int(time.time()), UID, BiliPushTargets([target], [], [], [])
    )
    await drain(owner)
    assert renderer.calls == []
    assert not any("TEXT_DIFF" in _text(message) for _, message in messenger.calls)


@pytest.mark.asyncio
async def test_pixel_identical_replacement_suppresses_the_entire_notice(
    tmp_path: Path,
) -> None:
    messenger, owner, renderer = Messenger(), TaskOwner(), EditRenderer(invisible=True)
    delivery, _, subscriptions = _delivery(messenger=messenger)
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    sender = BilibiliDynamicOutboundSender(
        delivery,
        cast("Any", subscriptions),
        ledger=ledger,
        spawn=owner.create,
        edit_renderer=cast("Any", renderer),
    )
    target = ConversationRef(Platform.ONEBOT, "group", "test-group")
    await sender.send(
        edited(text=False, media=True),
        int(time.time()),
        UID,
        BiliPushTargets([target], [], [], []),
    )
    await drain(owner)
    assert messenger.calls == []
    assert ledger.queue_ready() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_consecutive_edits_wait_for_original_and_preserve_version_order(
    tmp_path: Path, platform: Platform
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    class GatedMessenger(Messenger):
        async def send(self, conversation: ConversationRef, message: OutboundMessage):
            if not self.calls:
                entered.set()
                await release.wait()
            return await super().send(conversation, message)

    class VersionRenderer(EditRenderer):
        async def text(self, value: dict) -> OutboundMessage:
            return OutboundMessage.from_text(delivery_key(value))

    messenger, owner = GatedMessenger(), TaskOwner()
    delivery, _, subscriptions = _delivery(messenger=messenger)
    path = tmp_path / "ledger.sqlite"
    sender = BilibiliDynamicOutboundSender(
        delivery,
        cast("Any", subscriptions),
        ledger=SqliteDynamicDeliveryLedger(path),
        spawn=owner.create,
        edit_renderer=cast("Any", VersionRenderer()),
    )
    target = ConversationRef(platform, "group", "synthetic", account_id="test-bot")
    targets = BiliPushTargets([target], [], [], [])
    original = asyncio.create_task(sender.send(item(), int(time.time()), UID, targets))
    await asyncio.wait_for(entered.wait(), 5)
    for sequence in (1, 2):
        await sender.send(edited(sequence=sequence), int(time.time()), UID, targets)
    assert messenger.calls == []
    release.set()
    await original
    await drain(owner)
    messages = [_text(message) for _, message in messenger.calls]
    first = next(i for i, text in enumerate(messages) if "123456:edit:1" in text)
    second = next(i for i, text in enumerate(messages) if "123456:edit:2" in text)
    assert first < second
    restored = SqliteDynamicDeliveryLedger(path)
    assert restored.stage_state("123456:edit:1", target, "text") == "success"
    assert restored.stage_state("123456:edit:2", target, "text") == "success"


@pytest.mark.asyncio
async def test_uncertain_edit_blocks_its_body_but_releases_next_version(
    tmp_path: Path,
) -> None:
    class UncertainMessenger(Messenger):
        async def send(self, conversation: ConversationRef, message: OutboundMessage):
            self.calls.append((conversation, message))
            return SendResult(
                delivered=False, failure_kind=DeliveryFailureKind.UNCERTAIN
            )

    messenger, owner, renderer = UncertainMessenger(), TaskOwner(), EditRenderer()
    delivery, _, subscriptions = _delivery(messenger=messenger)
    sender = BilibiliDynamicOutboundSender(
        delivery,
        cast("Any", subscriptions),
        ledger=SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite"),
        spawn=owner.create,
        edit_renderer=cast("Any", renderer),
    )
    target = ConversationRef(Platform.ONEBOT, "group", "synthetic")
    targets = BiliPushTargets([target], [], [], [])
    sequences = (1, 2)
    for sequence in sequences:
        await sender.send(edited(sequence=sequence), int(time.time()), UID, targets)
    await drain(owner)
    assert len(messenger.calls) == len(sequences)
    assert all("动态已修改" in _text(message) for _, message in messenger.calls)
    assert not any("TEXT_DIFF" in _text(message) for _, message in messenger.calls)
    assert sender.ledger is not None
    assert all(
        sender.ledger.stage_state(f"123456:edit:{sequence}", target, "text")
        == "blocked"
        for sequence in sequences
    )


@pytest.mark.asyncio
async def test_image_text_fallback_is_frozen_across_restart(tmp_path: Path) -> None:
    renderer, owner = EditRenderer(), TaskOwner()
    delivery, _, subscriptions = _delivery(messenger=Messenger())
    path = tmp_path / "ledger.sqlite"
    sender = BilibiliDynamicOutboundSender(
        delivery,
        cast("Any", subscriptions),
        ledger=SqliteDynamicDeliveryLedger(path),
        spawn=owner.create,
        edit_renderer=cast("Any", renderer),
    )
    data = edited(text=False, media=True)
    first = await sender._prepare_frozen_images(data, delivery_key(data))
    restored = replace(sender, ledger=SqliteDynamicDeliveryLedger(path))
    second = await restored._prepare_frozen_images(data, delivery_key(data))
    assert first is not None and second is not None
    assert _text(first) == _text(second) == "IMAGE_DIFF"
    assert renderer.calls == ["image"]


@pytest.mark.asyncio
async def test_recovery_report_keeps_real_dynamic_id_separate_from_revision(
    tmp_path: Path,
) -> None:
    delivery, _, subscriptions = _delivery(messenger=Messenger())
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    data = edited()
    ledger.prepare(data, int(time.time()), UID, BiliPushTargets([], [], [], []), ())
    sender = BilibiliDynamicOutboundSender(
        delivery, cast("Any", subscriptions), ledger=ledger
    )
    notify = AsyncMock()
    recovery = BiliDeliveryRecovery(sender, cast("Any", object()), notify)
    await recovery._report(delivery_key(data), {"retry": 1})
    assert notify.await_args is not None
    body = notify.await_args.args[1]
    assert "动态ID：123456\n编辑版本：1\n" in body
    assert "动态ID：123456:edit:" not in body
