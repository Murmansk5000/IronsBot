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

    def __init__(self, message: list[FakeSegment], *, to_me: bool = False) -> None:
        self._message = message
        self._to_me = to_me

    def get_message(self) -> list[FakeSegment]:
        return self._message

    def is_tome(self) -> bool:
        return self._to_me


def test_mentions_bot_matches_direct_at() -> None:
    event = FakeGroupEvent([FakeSegment("at", {"qq": "100"})])

    assert mentions_bot(event)


def test_mentions_bot_does_not_treat_reply_as_mention() -> None:
    event = FakeGroupEvent([])
    event.reply = {"sender": {"user_id": 100}}

    assert not mentions_bot(event)
