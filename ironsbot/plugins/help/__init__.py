# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.shared.messaging import (
    finish_event_reply,
    send_event_reply,
)
from ironsbot.shared.messaging.replies import event_sender_at_user_ids
from ironsbot.shared.messaging.text import build_message
from ironsbot.utils.matcher import (
    enter_prompt_loop,
    prompt_session_manager,
    reject_with_rule,
)
from ironsbot.utils.rule import no_reply

from .menu import (
    HELP_ENTRIES_KEY,
    HelpMenuEntry,
    format_plugin_detail,
    format_plugin_list,
    visible_help_entries,
)

if TYPE_CHECKING:
    from ironsbot.config.models.app import AppConfig
    from ironsbot.runtime.matchers import MatcherRegistry
    from ironsbot.runtime.plugins import PluginDefinition
    from ironsbot.shared.features import FeatureService


def _help_prompt_message(event: Event, text: str):
    if not isinstance(event, MessageEvent):
        return text
    return build_message(text, at_user_ids=event_sender_at_user_ids(event))


async def _finish_help_reply(
    matcher: Matcher,
    event: Event,
    message: str,
) -> None:
    if isinstance(event, MessageEvent):
        await finish_event_reply(matcher, event, message)
        return
    await matcher.finish(message)


async def _send_help_reply(
    matcher: Matcher,
    event: Event,
    message: str,
) -> None:
    if isinstance(event, MessageEvent):
        await send_event_reply(matcher, event, message)
        return
    await matcher.send(message)


def _is_digit_input(event: Event) -> bool:
    if getattr(event, "reply", None) is not None:
        return False
    return event.get_plaintext().strip().isdigit()


async def handle_help(
    matcher: Matcher,
    event: Event,
    state: T_State,
    *,
    entries: list[HelpMenuEntry],
    features: FeatureService,
) -> None:
    if not entries:
        await _finish_help_reply(matcher, event, "当前会话没有可用的功能。")

    state[HELP_ENTRIES_KEY] = entries
    session_id = event.get_session_id()
    version = prompt_session_manager.acquire(session_id)
    rule = prompt_session_manager.make_rule(session_id, version, _is_digit_input)
    handler = _create_selection_handler(session_id, version, features)

    await enter_prompt_loop(
        matcher,
        handlers=[handler],
        rule=rule,
        prompt=_help_prompt_message(event, format_plugin_list(entries)),
    )


def _create_selection_handler(
    session_id: str,
    version: int,
    features: FeatureService,
) -> object:
    async def _handler(
        matcher: Matcher,
        event: Event,
        state: T_State,
    ) -> None:
        entries = state.get(HELP_ENTRIES_KEY)
        if not entries:
            raise FinishedException

        key_text = event.get_plaintext().strip()
        if key_text == "0":
            await _finish_help_reply(matcher, event, "✅ 已退出帮助。")

        if not key_text.isdigit():
            raise FinishedException

        index = int(key_text)
        if index < 1 or index > len(entries):
            await _finish_help_reply(matcher, event, "⚠️ 序号超出范围，已退出帮助。")

        await _send_help_reply(
            matcher,
            event,
            format_plugin_detail(entries[index - 1], event, features),
        )

        rule = prompt_session_manager.make_rule(session_id, version, _is_digit_input)
        await reject_with_rule(matcher, rule)

    return _handler


def install(
    registry: MatcherRegistry,
    definitions: tuple[PluginDefinition, ...],
    config: AppConfig,
    features: FeatureService,
    *,
    ai_key_configured: bool,
) -> None:
    matcher = registry.on_fullmatch(
        "帮助",
        policy=CommandPolicy.command("help"),
        rule=no_reply(),
        priority=registry.priority("help", 0),
        block=True,
    )

    async def _handle_help(
        matcher: Matcher,
        event: Event,
        state: T_State,
    ) -> None:
        entries = visible_help_entries(
            definitions,
            event,
            features=features,
            config=config,
            ai_key_configured=ai_key_configured,
        )
        await handle_help(
            matcher,
            event,
            state,
            entries=entries,
            features=features,
        )

    matcher.append_handler(_handle_help)
