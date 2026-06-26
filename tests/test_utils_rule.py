import asyncio
from dataclasses import dataclass
from typing import Any

from ironsbot.utils.rule import NoAt


@dataclass(slots=True)
class FakeSegment:
    type: str
    data: dict[str, Any] | None = None


@dataclass(slots=True)
class FakeEvent:
    message: list[FakeSegment] | None = None


def _matches_no_at(event: FakeEvent) -> bool:
    return asyncio.run(NoAt()(event, {}))


def test_no_at_allows_plain_text_messages() -> None:
    assert _matches_no_at(FakeEvent([FakeSegment("text", {"text": "帮助"})]))


def test_no_at_blocks_direct_bot_mentions() -> None:
    assert not _matches_no_at(
        FakeEvent(
            [
                FakeSegment("at", {"qq": "2947993138"}),
                FakeSegment("text", {"text": "帮助"}),
            ]
        )
    )


def test_no_at_blocks_foreign_mentions() -> None:
    assert not _matches_no_at(
        FakeEvent(
            [
                FakeSegment("at", {"qq": "123"}),
                FakeSegment("text", {"text": "帮助"}),
            ]
        )
    )
