from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ironsbot.services.ai.mentions import mentions_bot


@dataclass
class FakeSegment:
    type: str
    data: dict[str, Any]


class FakeGroupEvent:
    self_id = 100
    reply = None

    def __init__(
        self,
        message: list[FakeSegment],
        *,
        original_message: list[FakeSegment] | None = None,
        raw_message: str = "",
        to_me: bool = False,
    ) -> None:
        self._message = message
        self.original_message = original_message
        self.raw_message = raw_message
        self._to_me = to_me

    def get_message(self) -> list[FakeSegment]:
        return self._message

    def is_tome(self) -> bool:
        return self._to_me


def test_mentions_bot_matches_direct_at() -> None:
    event = FakeGroupEvent([FakeSegment("at", {"qq": "100"})])

    assert mentions_bot(event)


def test_mentions_bot_ignores_direct_at_when_message_is_reply() -> None:
    event = FakeGroupEvent([FakeSegment("at", {"qq": "100"})])
    event.reply = {"sender": {"user_id": 200}}

    assert not mentions_bot(event)


def test_mentions_bot_ignores_foreign_at() -> None:
    event = FakeGroupEvent([FakeSegment("at", {"qq": "200"})])

    assert not mentions_bot(event)


def test_mentions_bot_does_not_treat_reply_as_mention() -> None:
    event = FakeGroupEvent([])
    event.reply = {"sender": {"user_id": 100}}

    assert not mentions_bot(event)


def test_mentions_bot_treats_stripped_to_me_as_mention() -> None:
    event = FakeGroupEvent([], to_me=True)

    assert mentions_bot(event)


def test_mentions_bot_does_not_treat_reply_only_to_me_as_mention() -> None:
    event = FakeGroupEvent([], to_me=True)
    event.reply = {"sender": {"user_id": 100}}

    assert not mentions_bot(event)


def test_mentions_bot_matches_original_message_after_preprocessing() -> None:
    event = FakeGroupEvent(
        [],
        original_message=[FakeSegment("at", {"qq": "100"})],
    )

    assert mentions_bot(event)


def test_mentions_bot_ignores_original_message_at_when_message_is_reply() -> None:
    event = FakeGroupEvent(
        [],
        original_message=[FakeSegment("at", {"qq": "100"})],
    )
    event.reply = {"sender": {"user_id": 200}}

    assert not mentions_bot(event)


def test_mentions_bot_matches_raw_cq_at_after_preprocessing() -> None:
    event = FakeGroupEvent([], raw_message="[CQ:at,qq=100] ")

    assert mentions_bot(event)


def test_mentions_bot_ignores_raw_cq_at_when_message_is_reply() -> None:
    event = FakeGroupEvent([], raw_message="[CQ:at,qq=100] ")
    event.reply = {"sender": {"user_id": 200}}

    assert not mentions_bot(event)
