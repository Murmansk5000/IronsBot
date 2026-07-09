import asyncio
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from nonebot.adapters.onebot.v11 import MessageEvent
from pytest import MonkeyPatch

from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from nonebot.adapters import Event

_MODULE_PATH = (
    Path(__file__).parents[1]
    / "ironsbot"
    / "plugins"
    / "seer"
    / "query"
    / "commands"
    / "query_replies.py"
)
_SPEC = spec_from_file_location("seer_query_replies_for_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
query_replies = module_from_spec(_SPEC)
_SPEC.loader.exec_module(query_replies)


class FakeMatcher:
    def __init__(self) -> None:
        self.finished_messages: list[object] = []

    async def finish(self, message: object | None = None) -> None:
        self.finished_messages.append(message)


def test_finish_query_reply_uses_event_reply_for_message_events(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[tuple[Any, MessageEvent, object]] = []

    async def fake_finish_event_reply(
        matcher: Any,
        event: MessageEvent,
        message: object,
    ) -> None:
        calls.append((matcher, event, message))

    monkeypatch.setattr(query_replies, "finish_event_reply", fake_finish_event_reply)

    matcher = FakeMatcher()
    event = group_message_event("帮助")

    asyncio.run(query_replies.finish_query_reply(matcher, event, "帮助文本"))

    assert calls == [(matcher, event, "帮助文本")]
    assert matcher.finished_messages == []


def test_finish_query_reply_finishes_plain_events_without_message_context() -> None:
    matcher = FakeMatcher()
    event = cast("Event", object())

    asyncio.run(query_replies.finish_query_reply(matcher, event, "普通回复"))

    assert matcher.finished_messages == ["普通回复"]
