# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.runtime.matchers import (
    CommandPolicy,
    enter_prompt_loop,
    get_prompt_session_manager,
    reject_with_rule,
)
from ironsbot.runtime.replies import (
    build_message,
    event_sender_at_user_ids,
    finish_event_reply,
    send_event_reply,
)
from ironsbot.runtime.rules import no_reply

from .menu import (
    HELP_ENTRIES_KEY,
    HelpMenuEntry,
    format_plugin_detail,
    format_plugin_list,
    visible_help_entries,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event

    from ironsbot.core.features import FeatureService
    from ironsbot.runtime.commands import CommandCatalog
    from ironsbot.runtime.matchers import MatcherRegistry
    from ironsbot.runtime.plugins import PluginDefinition


def _help_prompt_message(event: MessageEvent, text: str):
    return build_message(text, at_user_ids=event_sender_at_user_ids(event))


def _is_digit_input(event: Event) -> bool:
    if not isinstance(event, MessageEvent):
        return False
    return event.get_plaintext().strip().isdigit()


async def handle_help(  # noqa: PLR0913
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    entries: list[HelpMenuEntry],
    features: FeatureService,
    commands: CommandCatalog,
    ignored_plugins: tuple[str, ...],
) -> None:
    if not entries:
        await finish_event_reply(matcher, event, "当前会话没有可用的功能。")

    state[HELP_ENTRIES_KEY] = entries
    session_id = event.get_session_id()
    prompt_sessions = get_prompt_session_manager(matcher)
    version = prompt_sessions.acquire(session_id)
    rule = prompt_sessions.make_rule(session_id, version, _is_digit_input)
    handler = _create_selection_handler(
        session_id,
        version,
        features,
        commands,
        ignored_plugins,
    )

    await enter_prompt_loop(
        matcher,
        handlers=[handler],
        rule=rule,
        prompt=_help_prompt_message(event, format_plugin_list(entries)),
        queue_namespace="help",
        queue_reply_check=lambda next_event: (
            next_event.get_session_id() == session_id
            and getattr(next_event, "reply", None) is None
            and _is_digit_input(next_event)
        ),
        queue_group_reply_check=_is_digit_input,
    )


def _create_selection_handler(
    session_id: str,
    version: int,
    features: FeatureService,
    commands: CommandCatalog,
    ignored_plugins: tuple[str, ...],
) -> object:
    async def _handler(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        entries = state.get(HELP_ENTRIES_KEY)
        if not entries:
            raise FinishedException

        key_text = event.get_plaintext().strip()
        if key_text == "0":
            await finish_event_reply(matcher, event, "✅ 已退出帮助。")

        if not key_text.isdigit():
            raise FinishedException

        index = int(key_text)
        if index < 1 or index > len(entries):
            await finish_event_reply(
                matcher,
                event,
                "⚠️ 序号超出范围，已退出帮助。",
            )

        await send_event_reply(
            matcher,
            event,
            format_plugin_detail(
                entries[index - 1],
                event,
                features,
                commands,
                ignored_plugins=ignored_plugins,
            ),
        )

        rule = get_prompt_session_manager(matcher).make_rule(
            session_id,
            version,
            _is_digit_input,
        )
        await reject_with_rule(matcher, rule)

    return _handler


def install(
    registry: MatcherRegistry,
    definitions: tuple[PluginDefinition, ...],
    features: FeatureService,
    commands: CommandCatalog,
    *,
    ignored_plugins: tuple[str, ...],
) -> None:
    matcher = registry.on_fullmatch(
        "帮助",
        policy=CommandPolicy.command("help", help_ids=("help",)),
        rule=no_reply(),
        priority=registry.priority("help"),
        block=True,
    )

    async def _handle_help(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        entries = visible_help_entries(
            definitions,
            event,
            features=features,
            commands=commands,
            ignored_plugins=ignored_plugins,
        )
        await handle_help(
            matcher,
            event,
            state,
            entries=entries,
            features=features,
            commands=commands,
            ignored_plugins=ignored_plugins,
        )

    matcher.append_handler(_handle_help)
