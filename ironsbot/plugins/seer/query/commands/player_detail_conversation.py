# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, cast

from nonebot.adapters import Event  # noqa: TC002
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.runtime.conversations import (
    command_reply_check,
    enter_event_reply_conversation,
)
from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import bind_async
from ironsbot.runtime.onebot_context import event_group_id
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.services.seer.player_detail_extensions import (  # noqa: TC001
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_query import (
    PLAYER_AUTOCARD_KEY,
    PLAYER_COLLECTION_KEY,
    PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY,
    PLAYER_DETAIL_COMMANDS_KEY,
    PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY,
    PLAYER_PEAK_KEY,
    cached_player_detail_message,
    is_player_detail_exit,
    plan_player_detail_prompt,
    resolve_player_detail_reply,
)
from ironsbot.services.seer.player_service import PlayerService  # noqa: TC001
from ironsbot.services.seer.player_shortcuts import PlayerShortcutCommand

from .player_context import PLAYER_DETAIL_NAMESPACE, PLAYER_ID_KEY

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.features import FeatureService
    from ironsbot.services.seer.player_shortcuts import PlayerShortcutKind
    from ironsbot.services.seer.query_result import QueryReply

_SHORTCUT_KINDS = {
    PLAYER_COLLECTION_KEY: "collection",
    PLAYER_PEAK_KEY: "peak",
    PLAYER_AUTOCARD_KEY: "autocard",
}
_SELECTION_PAIR_LENGTH = 2


async def handle_player_detail_reply(
    service: PlayerService,
    extensions: PlayerDetailExtensionRegistry,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    if is_player_detail_exit(event.get_plaintext()):
        await finish_event_reply(matcher, event, "已退出米米号详情查询。")
        return

    extension_action = _resolve_player_detail_extension_action(
        extensions,
        event.get_plaintext(),
        state,
    )
    detail_request = (
        None
        if extension_action is not None
        else resolve_player_detail_reply(
            event.get_plaintext(),
            selections=_stored_player_detail_selections(
                state,
                PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY,
            ),
        )
    )
    if detail_request is None and extension_action is None:
        raise FinishedException

    player_id = state.get(PLAYER_ID_KEY)
    if not isinstance(player_id, int):
        raise FinishedException

    if extension_action is not None:
        reply = await extension_action.query(
            player_id,
            event.user_id,
            event_group_id(event),
        )
        await _continue_player_detail_conversation(
            service,
            extensions,
            matcher,
            event,
            state,
            prompt=_query_reply_message(reply),
        )
        return

    if detail_request is None:
        raise FinishedException

    message = cached_player_detail_message(state, detail_request.key)
    if not message:
        kind = cast("PlayerShortcutKind", _SHORTCUT_KINDS[detail_request.key])
        if _is_detail_inflight(service, player_id, kind):
            await send_event_reply(
                matcher,
                event,
                _inflight_detail_message(detail_request.label),
            )

        reply = await service.shortcut(
            PlayerShortcutCommand(kind=kind, player_id=player_id),
            event.user_id,
            group_id=event_group_id(event),
        )
        message = _reply_text(reply.leading_text, reply.text, reply.image_error)
        state[detail_request.key] = message

    await _continue_player_detail_conversation(
        service,
        extensions,
        matcher,
        event,
        state,
        prompt=message,
    )


async def send_player_info_with_detail_prompt(  # noqa: PLR0913
    service: PlayerService,
    features: FeatureService,
    extensions: PlayerDetailExtensionRegistry,
    matcher: Matcher,
    event: Event,
    state: T_State,
    *,
    player_id: int,
    player_message: str,
    has_collection: bool = False,
    has_peak: bool = False,
    has_autocard: bool = False,
    on_sent: Callable[[], None] | None = None,
) -> None:
    state[PLAYER_ID_KEY] = player_id
    for detail_key in _SHORTCUT_KINDS:
        state.pop(detail_key, None)

    visible_extensions = tuple(
        action
        for action in extensions.actions()
        if event_is_feature_allowed(features, event, action.feature)
    )
    prompt_plan = plan_player_detail_prompt(
        has_collection=has_collection,
        has_peak=has_peak,
        has_autocard=has_autocard,
        supports_conversation=isinstance(event, MessageEvent),
        extension_actions=visible_extensions,
    )
    state[PLAYER_DETAIL_COMMANDS_KEY] = prompt_plan.accepted_commands
    state[PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY] = prompt_plan.builtin_selections
    state[PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY] = prompt_plan.extension_selections
    prompt = "\n".join((player_message, *prompt_plan.prompt_lines))

    try:
        if not prompt_plan.should_enter_conversation:
            if isinstance(event, MessageEvent):
                await finish_event_reply(matcher, event, prompt)
            else:
                await matcher.finish(prompt)
        elif not isinstance(event, MessageEvent):
            await matcher.finish(prompt)
        else:
            await enter_event_reply_conversation(
                matcher,
                event,
                namespace=PLAYER_DETAIL_NAMESPACE,
                handlers=[bind_async(handle_player_detail_reply, service, extensions)],
                reply_check=command_reply_check(prompt_plan.accepted_commands),
                prompt=prompt,
            )
    except FinishedException:
        if on_sent is not None:
            on_sent()
        raise
    else:
        if on_sent is not None:
            on_sent()


async def _continue_player_detail_conversation(  # noqa: PLR0913
    service: PlayerService,
    extensions: PlayerDetailExtensionRegistry,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    prompt: str | Message | None,
) -> None:
    commands = tuple(state.get(PLAYER_DETAIL_COMMANDS_KEY) or ())
    if not commands:
        if prompt is None:
            raise FinishedException
        await finish_event_reply(matcher, event, prompt)

    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=PLAYER_DETAIL_NAMESPACE,
        handlers=[bind_async(handle_player_detail_reply, service, extensions)],
        reply_check=command_reply_check(commands),
        prompt=prompt,
    )


def _reply_text(leading_text: str, text: str, image_error: str) -> str:
    return f"{leading_text}{text or image_error}"


def _query_reply_message(reply: QueryReply) -> str | Message:
    if reply.image is None:
        return _reply_text(reply.leading_text, reply.text, reply.image_error)

    message = Message()
    if reply.leading_text:
        message += MessageSegment.text(reply.leading_text)
    message += MessageSegment.image(reply.image)
    if reply.text:
        message += MessageSegment.text(reply.text)
    elif reply.image_error:
        message += MessageSegment.text(reply.image_error)
    return message


def _is_detail_inflight(
    service: PlayerService,
    player_id: int,
    kind: PlayerShortcutKind,
) -> bool:
    has_inflight = getattr(service, "has_inflight_detail", None)
    if not callable(has_inflight):
        return False
    return bool(has_inflight(player_id, kind))


def _inflight_detail_message(label: str) -> str:
    return (
        f"⏳ {label}正在查询，完成后会直接发送结果。\n"
        "数据较多时可能需要排队，请稍候。"
    )


def _resolve_player_detail_extension_action(
    extensions: PlayerDetailExtensionRegistry,
    text_value: str,
    state: T_State,
):
    selections = _stored_player_detail_selections(
        state,
        PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY,
    )
    selection_ids = dict(selections)
    selection = _normalize_detail_command_text(text_value)
    action = extensions.get(selection_ids.get(selection, ""))
    if action is not None:
        return action
    return extensions.resolve_alias(
        text_value,
        allowed_ids=tuple(selection_ids.values()),
    )


def _stored_player_detail_selections(
    state: T_State,
    key: str,
) -> tuple[tuple[str, str], ...]:
    raw_selections = state.get(key)
    if not isinstance(raw_selections, tuple):
        return ()
    return tuple(
        (selection, action_id)
        for item in raw_selections
        if isinstance(item, tuple)
        and len(item) == _SELECTION_PAIR_LENGTH
        and isinstance(selection := item[0], str)
        and isinstance(action_id := item[1], str)
    )


def _normalize_detail_command_text(text_value: str) -> str:
    return "".join(text_value.split()).casefold()
