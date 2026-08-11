from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

from ironsbot.plugins.seer.query.commands import autocard_sanctuary as plugin
from ironsbot.services.seer.autocard_sanctuary import (
    Sanctuary,
    SanctuaryEffect,
    SanctuaryEffectEntry,
    SanctuaryPromptValue,
    SanctuarySearchResult,
)


class _Service:
    def __init__(self, result: SanctuarySearchResult) -> None:
        self._result = result

    def search(self, _arg: str) -> SanctuarySearchResult:
        return self._result

    def select(self, _value: SanctuaryPromptValue) -> SanctuarySearchResult:
        return self._result


def _sanctuary() -> Sanctuary:
    return Sanctuary(
        id=2,
        name="沧岚",
        pet_id=3105,
        pet_name="沧岚",
        effects=(
            SanctuaryEffect(8, 2, "沧岚", "基础效果", 0, 0),
            SanctuaryEffect(9, 2, "潮涌", "祝印效果", 5, 1),
        ),
    )


def test_direct_sanctuary_query_opens_its_numbered_effect_menu(
    monkeypatch: Any,
) -> None:
    captured: list[dict[str, object]] = []

    async def enter(*_args: object, **kwargs: object) -> None:
        captured.append(dict(kwargs))

    monkeypatch.setattr(plugin, "_invalidate_sanctuary_prompt", lambda *_args: None)
    monkeypatch.setattr(plugin, "enter_event_reply_conversation", enter)
    matcher = SimpleNamespace(state={})
    event = SimpleNamespace()
    state = {"_irons_bot_command_arg": "沧岚"}

    asyncio.run(
        plugin.handle_autocard_sanctuary_query(
            cast("Any", _Service(SanctuarySearchResult(sanctuary=_sanctuary()))),
            cast("Any", matcher),
            cast("Any", event),
            cast("Any", state),
        )
    )

    assert captured[0]["namespace"] == plugin.SANCTUARY_PROMPT_NAMESPACE
    assert captured[0]["prompt"] is not None
    assert matcher.state[plugin.SANCTUARY_PROMPT_STATE_KEY] == (
        SanctuaryPromptValue("effect", 2, 8),
        SanctuaryPromptValue("effect", 2, 9),
    )


def test_effect_selection_sends_detail_and_keeps_the_current_menu(
    monkeypatch: Any,
) -> None:
    replies: list[str] = []
    prompts: list[dict[str, object]] = []

    async def send_reply(_matcher: object, _event: object, message: str) -> None:
        replies.append(message)

    async def enter(*_args: object, **kwargs: object) -> None:
        prompts.append(dict(kwargs))

    monkeypatch.setattr(plugin, "send_event_reply", send_reply)
    monkeypatch.setattr(plugin, "enter_event_reply_conversation", enter)
    value = SanctuaryPromptValue("effect", 2, 9)
    matcher = SimpleNamespace(
        state={plugin.SANCTUARY_PROMPT_STATE_KEY: (value,)}
    )
    event = SimpleNamespace(get_plaintext=lambda: "1")
    result = SanctuarySearchResult(
        effect=SanctuaryEffectEntry(9, "潮涌", "完整祝印描述")
    )

    asyncio.run(
        plugin._handle_sanctuary_prompt_reply(
            cast("Any", _Service(result)),
            cast("Any", matcher),
            cast("Any", event),
            cast("Any", matcher.state),
        )
    )

    assert replies == ["完整祝印描述"]
    assert prompts[0]["prompt"] is None
    assert matcher.state[plugin.SANCTUARY_PROMPT_STATE_KEY] == (value,)
