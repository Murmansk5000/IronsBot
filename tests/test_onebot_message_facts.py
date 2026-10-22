from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.core.message_input import MessageInputKind
from ironsbot.integrations.onebot.message_envelope import decode_received_message
from ironsbot.integrations.onebot.message_facts import (
    OneBotMessageFacts,
    decode_onebot_message,
)
from tests.helpers.onebot_events import group_message_event, private_message_event
from tests.helpers.onebot_inputs import message_input_context

if TYPE_CHECKING:
    from ironsbot.integrations.onebot.message_segments import OneBotSegment


@pytest.mark.parametrize(
    "member,bot,reply,expected",
    [
        (False, False, False, MessageInputKind.DIRECT),
        (True, False, False, MessageInputKind.MEMBER_MENTION),
        (False, True, False, MessageInputKind.BOT_MENTION),
        (True, True, False, MessageInputKind.BOT_MENTION),
        (False, False, True, MessageInputKind.REPLY),
        (True, True, True, MessageInputKind.REPLY),
    ],
)
def test_protocol_context_preserves_mention_facts_alongside_input_kind(
    *, member: bool, bot: bool, reply: bool, expected: MessageInputKind
) -> None:
    segments: list[OneBotSegment] = []
    if member:
        segments.append({"type": "at", "data": {"qq": "456"}})
    if bot:
        segments.append({"type": "at", "data": {"qq": "1"}})
    if reply:
        segments.append({"type": "reply", "data": {"id": "99"}})
    facts = OneBotMessageFacts(
        account_id="1",
        user_id="123",
        message_id="3",
        text="current",
        group_id="456",
        segments=tuple(segments),
    )
    context = decode_onebot_message(facts)
    assert context.kind is expected
    assert context.mentions_bot is bot
    assert tuple(actor.id for actor in context.member_mentions) == (
        ("456",) if member else ()
    )
    assert context.message.reply_to_id == ("99" if reply else None)


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize(
    "mode", ["direct", "bot", "member", "everyone", "reply", "original", "to_me", "raw"]
)
def test_native_facts_match_the_protocol_decoder(mode: str, *, private: bool) -> None:
    message = Message("current")
    if mode == "bot":
        message = MessageSegment.at(1) + message
    elif mode == "member":
        message = MessageSegment.at(777) + MessageSegment.at(777) + message
    elif mode == "everyone":
        message = MessageSegment.at("all") + message
    elif mode == "reply":
        message = MessageSegment.reply(-12) + message
    original = (
        MessageSegment.at(1) + MessageSegment.at(777) + message
        if mode == "original"
        else message
    )
    event = private_message_event() if private else group_message_event()
    event.message = message
    event.original_message = original
    event.raw_message = "[CQ:at,qq=1]current" if mode == "raw" else str(message)
    event.to_me = mode == "to_me"
    current_segments: tuple[OneBotSegment, ...] = tuple(
        {"type": part.type, "data": part.data} for part in message
    )
    original_segments: tuple[OneBotSegment, ...] = tuple(
        {"type": part.type, "data": part.data} for part in original
    )
    facts = OneBotMessageFacts(
        account_id="1",
        user_id="123",
        message_id="3",
        text="current",
        segments=current_segments,
        original_segments=original_segments,
        group_id=None if private else "456",
        raw_message=event.raw_message,
        addressed_to_bot=not private and mode == "to_me",
    )
    decoded = decode_onebot_message(facts)
    assert message_input_context(event) == decoded
    assert decoded.text == "current"
    assert decoded.mentions_bot is (
        mode in {"bot", "original", "raw"} or (mode == "to_me" and not private)
    )
    assert decoded.mentions_everyone is (mode == "everyone")
    assert tuple(actor.id for actor in decoded.member_mentions) == (
        ("777",) if mode in {"member", "original"} else ()
    )
    assert decoded.message.reply_to_id == ("-12" if mode == "reply" else None)


def test_reply_metadata_does_not_import_quoted_text_or_mentions() -> None:
    event = group_message_event(
        "current",
        reply_sender_user_id=333,
        reply_message_id=-12,
    )
    assert event.reply is not None
    event.reply.message = MessageSegment.at(1) + MessageSegment.at(888) + "quoted"
    facts = OneBotMessageFacts(
        account_id="1",
        user_id="123",
        message_id="3",
        text="current",
        reply_to_id="-12",
        group_id="456",
        segments=({"type": "text", "data": {"text": "current"}},),
    )
    result = message_input_context(event)
    assert result == decode_onebot_message(facts)
    assert result.text == "current"
    assert not result.has_any_mention
    assert result.message.reply_to_id == "-12"


@pytest.mark.parametrize("private", [False, True])
def test_sender_label_and_role_remain_separate_from_conversation_type(
    *, private: bool
) -> None:
    sender = {"nickname": " nickname ", "card": "card", "role": "admin"}
    event = (
        private_message_event("current", sender=sender)
        if private
        else group_message_event("current", sender=sender)
    )
    facts = OneBotMessageFacts(
        account_id="1",
        user_id="123",
        message_id="3",
        text="current",
        group_id=None if private else "456",
        group_role="admin",
        actor_display_name=" nickname ",
    )
    result = message_input_context(event)
    assert result == decode_onebot_message(facts)
    assert result.actor_display_name == "nickname"
    assert result.message.group_role == (None if private else "admin")


@pytest.mark.parametrize("metadata", [None, "0", "-3"])
def test_metadata_then_current_then_original_reply_precedence(
    metadata: str | None,
) -> None:
    facts = OneBotMessageFacts(
        account_id="1",
        user_id="123",
        message_id="3",
        text="current",
        reply_to_id=metadata,
        segments=({"type": "reply", "data": {"id": "-1"}},),
        original_segments=({"type": "reply", "data": {"id": "-2"}},),
    )
    assert decode_onebot_message(facts).message.reply_to_id == (
        metadata if metadata is not None else "-1"
    )
    without_current = replace(facts, reply_to_id=None, segments=())
    assert decode_onebot_message(without_current).message.reply_to_id == "-2"


@pytest.mark.parametrize("field", ["user_id", "message_id", "reply"])
def test_received_missing_required_metadata_is_rejected(field: str) -> None:
    payload = group_message_event().model_dump()
    payload[field] = {"message_id": None} if field == "reply" else None
    assert decode_received_message(payload) is None


def test_protocol_decoder_and_admission_run_without_nonebot() -> None:
    script = """
import asyncio
import importlib.abc
import sys
from dataclasses import replace

class RejectNoneBot(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'nonebot' or fullname.startswith('nonebot.'):
            raise AssertionError('unexpected framework dependency: ' + fullname)
sys.meta_path.insert(0, RejectNoneBot())

from ironsbot.core.feature_policy import FeatureService
from ironsbot.integrations.onebot.message_facts import (
    OneBotMessageFacts, decode_onebot_message,
)
from ironsbot.services.onebot_admission import (
    AdmissionRejection, OneBotAdmissionService, OneBotAdmissionInput,
)

async def run():
    facts = OneBotMessageFacts(
        account_id='1', user_id='123', message_id='-3', text='current', group_id='456',
        segments=(
            {'type': 'reply', 'data': {'id': '-12'}},
            {'type': 'at', 'data': {'qq': '1'}},
            {'type': 'at', 'data': {'qq': '777'}},
        ),
    )
    context = decode_onebot_message(facts)
    assert context.mentions_bot and context.message.reply_to_id == '-12'
    assert tuple(actor.id for actor in context.member_mentions) == ('777',)
    service = OneBotAdmissionService(True, FeatureService({}, {}, frozenset()))
    decision = await service.decide(
        OneBotAdmissionInput(context, is_group_message=True)
    )
    assert decision.rejection is None
    everyone = decode_onebot_message(replace(facts, segments=(
        {'type': 'at', 'data': {'qq': 'all'}},
    )))
    decision = await service.decide(
        OneBotAdmissionInput(everyone, is_group_message=True)
    )
    assert decision.rejection is AdmissionRejection.EVERYONE

asyncio.run(run())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
