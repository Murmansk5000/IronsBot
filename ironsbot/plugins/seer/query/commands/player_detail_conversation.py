# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING, cast

from nonebot.adapters import Event  # noqa: TC002
from nonebot.adapters.onebot.v11 import Message, MessageEvent, MessageSegment
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.core.features import FeatureService  # noqa: TC001
from ironsbot.core.request_coordination import (
    RequestDecision,
    request_response_scope,
)
from ironsbot.runtime.conversations import (
    begin_event_reply_conversation,
    command_reply_check,
    enter_event_reply_conversation,
)
from ironsbot.runtime.feature_policy import event_is_feature_allowed
from ironsbot.runtime.matchers import (
    bind_async,
    get_prompt_session_manager,
)
from ironsbot.runtime.onebot_context import event_group_id
from ironsbot.runtime.prompt_sessions import (
    QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY,
    QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY,
)
from ironsbot.runtime.replies import finish_event_reply, send_event_reply
from ironsbot.runtime.semantic_requests import (
    SemanticRequest,
    SemanticRequestSource,
)
from ironsbot.services.seer.player_detail_extensions import (  # noqa: TC001
    PlayerDetailExtensionAction,
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_query import (
    PLAYER_AUTOCARD_KEY,
    PLAYER_COLLECTION_KEY,
    PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY,
    PLAYER_DETAIL_COMMANDS_KEY,
    PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY,
    PLAYER_PEAK_KEY,
    is_player_detail_exit,
    plan_player_detail_prompt,
    resolve_player_detail_reply,
)
from ironsbot.services.seer.player_service import PlayerService  # noqa: TC001
from ironsbot.services.seer.player_shortcuts import (
    PlayerShortcutCommand,
    execute_player_shortcut,
    player_request_admission_message,
    player_shortcut_semantic_request,
)
from ironsbot.services.seer.query_work import QueryWorkMeter, query_work_scope

from .player_context import (
    PLAYER_DETAIL_MENU_CONTEXT_KEY,
    PLAYER_DETAIL_NAMESPACE,
    PLAYER_ID_KEY,
    PlayerDetailMenuContext,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.services.seer.player_service_models import PlayerBaseSnapshot
    from ironsbot.services.seer.player_shortcuts import PlayerShortcutKind
    from ironsbot.services.seer.query_result import QueryReply

_SHORTCUT_KINDS = {
    PLAYER_COLLECTION_KEY: "collection",
    PLAYER_PEAK_KEY: "peak",
    PLAYER_AUTOCARD_KEY: "autocard",
}
_SELECTION_PAIR_LENGTH = 2


def _is_pending_player_detail_reply(event: MessageEvent) -> bool:
    """Recognize only the stable numeric shape before menu capabilities are known."""

    return event.get_plaintext().strip().isdigit()


async def begin_player_detail_conversation(
    service: PlayerService,
    extensions: PlayerDetailExtensionRegistry,
    features: FeatureService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    """Accept fast numeric detail choices while the base profile is loading."""

    await begin_event_reply_conversation(
        matcher,
        event,
        namespace=PLAYER_DETAIL_NAMESPACE,
        handlers=[
            bind_async(
                handle_player_detail_reply,
                service,
                extensions,
                features,
            )
        ],
        pending_reply_check=_is_pending_player_detail_reply,
        reply_check=_is_pending_player_detail_reply,
        parallel=True,
        queue_semantic_request_resolver=partial(
            _player_detail_semantic_request,
            extensions,
            features,
        ),
        page_id="player:detail",
    )


async def reserve_player_detail_conversation(
    service: PlayerService,
    extensions: PlayerDetailExtensionRegistry,
    features: FeatureService,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    """Reserve numeric replies before the slower player command starts."""

    prompt_sessions = get_prompt_session_manager(matcher)
    prompt_sessions.invalidate_event_conversations(event)
    await begin_player_detail_conversation(
        service,
        extensions,
        features,
        matcher,
        event,
    )
    matcher.state[QUEUED_CONVERSATION_KEEP_OPEN_STATE_KEY] = True


async def handle_player_detail_reply(  # noqa: PLR0913
    service: PlayerService,
    extensions: PlayerDetailExtensionRegistry,
    features: FeatureService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    _ignore_shared_player_detail_exit(event, state)
    is_shared_reply = bool(state.get(QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY))
    shared_reply = _take_shared_menu_reply(matcher, state)
    source_selection = _selected_player_detail_action(
        extensions,
        event.get_plaintext(),
        state,
    )
    if is_shared_reply and shared_reply is None:
        await finish_event_reply(matcher, event, "该菜单已失效，请重新查询米米号。")
        return
    if shared_reply is not None:
        _configure_player_detail_state(
            features,
            extensions,
            event,
            state,
            shared_reply,
        )
        if not is_player_detail_exit(event.get_plaintext()) and (
            source_selection
            != _selected_player_detail_action(extensions, event.get_plaintext(), state)
        ):
            await finish_event_reply(matcher, event, "该功能当前未对你开放。")
            return

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
        reply = await _query_extension_action(
            extension_action,
            matcher,
            event,
            player_id=player_id,
        )
        await _deliver_player_detail_result(
            service,
            extensions,
            features,
            matcher,
            event,
            state,
            keep_menu_context=is_shared_reply,
            action=extension_action.action.id,
            prompt=_query_reply_message(reply),
            on_sent=lambda: service.record_returned_detail_reply(
                qq_user_id=event.user_id,
                player_id=player_id,
                action_key=extension_action.action.id,
                reply=reply,
            ),
        )
        return

    if detail_request is None:
        raise FinishedException

    kind = cast("PlayerShortcutKind", _SHORTCUT_KINDS[detail_request.key])
    menu_context = state.get(PLAYER_DETAIL_MENU_CONTEXT_KEY)
    base_snapshot = (
        menu_context.base_snapshot
        if isinstance(menu_context, PlayerDetailMenuContext)
        else None
    )

    async def send_status(message: str) -> None:
        await send_event_reply(matcher, event, message)

    reply = await execute_player_shortcut(
        service,
        PlayerShortcutCommand(
            kind=kind,
            player_id=player_id,
            base_snapshot=base_snapshot,
        ),
        event.user_id,
        group_id=event_group_id(event),
        send_status=send_status,
    )
    message = _reply_text(reply.leading_text, reply.text, reply.image_error)

    await _deliver_player_detail_result(
        service,
        extensions,
        features,
        matcher,
        event,
        state,
        keep_menu_context=is_shared_reply,
        action=kind,
        prompt=message,
        on_sent=lambda: service.record_returned_shortcut(
            event.user_id,
            PlayerShortcutCommand(kind=kind, player_id=player_id),
            reply,
        ),
    )


async def _query_extension_action(
    action: PlayerDetailExtensionAction,
    matcher: Matcher,
    event: MessageEvent,
    *,
    player_id: int,
) -> QueryReply:
    async def send_status(decision: RequestDecision) -> None:
        await send_event_reply(
            matcher,
            event,
            player_request_admission_message(
                decision.label,
                queued=decision.queued,
            ),
        )

    meter = QueryWorkMeter("foreground")
    with (
        request_response_scope(action.action.label, send_status),
        query_work_scope(meter),
    ):
        reply = await action.query(
            player_id,
            event.user_id,
            event_group_id(event),
        )
    if reply.complete and (reply.text or reply.image is not None):
        meter.succeeded(action.work_unit)
    return replace(reply, query_work=meter.result())


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
    base_snapshot: PlayerBaseSnapshot | None = None,
    on_sent: Callable[[], None] | None = None,
) -> None:
    prompt_plan = _configure_player_detail_state(
        features,
        extensions,
        event,
        state,
        PlayerDetailMenuContext(
            player_id=player_id,
            has_collection=has_collection,
            has_peak=has_peak,
            has_autocard=has_autocard,
            base_snapshot=base_snapshot,
        ),
    )
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
                handlers=[
                    bind_async(
                        handle_player_detail_reply,
                        service,
                        extensions,
                        features,
                    )
                ],
                reply_check=command_reply_check(prompt_plan.accepted_commands),
                prompt=prompt,
                group_reply_check=_player_detail_group_reply_check(
                    features,
                    prompt_plan.accepted_commands,
                ),
                allow_group_reply_exit=True,
                parallel=True,
                page_id="player:detail",
                queue_semantic_request_resolver=partial(
                    _player_detail_semantic_request,
                    extensions,
                    features,
                ),
            )
    except FinishedException:
        if on_sent is not None:
            on_sent()
        raise
    else:
        if on_sent is not None:
            on_sent()


async def _deliver_player_detail_result(  # noqa: PLR0913
    service: PlayerService,
    extensions: PlayerDetailExtensionRegistry,
    features: FeatureService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    keep_menu_context: bool,
    action: str,
    prompt: str | Message | None,
    on_sent: Callable[[], None] | None = None,
) -> None:
    if keep_menu_context:
        await _continue_player_detail_conversation(
            service,
            extensions,
            features,
            matcher,
            event,
            state,
            prompt=prompt,
            on_sent=on_sent,
        )
        return
    await _finish_player_detail_result(
        matcher,
        event,
        action=action,
        prompt=prompt,
        on_sent=on_sent,
    )


async def _finish_player_detail_result(
    matcher: Matcher,
    event: MessageEvent,
    *,
    action: str,
    prompt: str | Message | None,
    on_sent: Callable[[], None] | None = None,
) -> None:
    """Send one parallel result without reopening the original player menu."""

    if prompt is None:
        raise FinishedException
    try:
        await finish_event_reply(matcher, event, prompt)
    except FinishedException:
        logger.info(
            "player detail result sent without reopening menu: user={} "
            "message_id={} action={}",
            event.user_id,
            event.message_id,
            action,
        )
        if on_sent is not None:
            on_sent()
        raise
    logger.info(
        "player detail result sent without reopening menu: user={} "
        "message_id={} action={}",
        event.user_id,
        event.message_id,
        action,
    )
    if on_sent is not None:
        on_sent()


async def _continue_player_detail_conversation(  # noqa: PLR0913
    service: PlayerService,
    extensions: PlayerDetailExtensionRegistry,
    features: FeatureService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    *,
    prompt: str | Message | None,
    on_sent: Callable[[], None] | None = None,
) -> None:
    """Open a separate menu only for a member using someone else's menu."""

    commands = tuple(state.get(PLAYER_DETAIL_COMMANDS_KEY) or ())
    if not commands:
        if prompt is None:
            raise FinishedException
        try:
            await finish_event_reply(matcher, event, prompt)
        except FinishedException:
            if on_sent is not None:
                on_sent()
            raise
        if on_sent is not None:
            on_sent()
        return

    try:
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=PLAYER_DETAIL_NAMESPACE,
            handlers=[
                bind_async(handle_player_detail_reply, service, extensions, features)
            ],
            reply_check=command_reply_check(commands),
            prompt=prompt,
            group_reply_check=_player_detail_group_reply_check(features, commands),
            allow_group_reply_exit=True,
            parallel=True,
            page_id="player:detail",
            queue_semantic_request_resolver=partial(
                _player_detail_semantic_request,
                extensions,
                features,
            ),
        )
    except FinishedException:
        if on_sent is not None:
            on_sent()
        raise
    if on_sent is not None:
        on_sent()


def _ignore_shared_player_detail_exit(
    event: MessageEvent,
    state: T_State,
) -> None:
    """Never let a member replying to another user's menu close it."""

    if bool(state.get(QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY)) and (
        is_player_detail_exit(event.get_plaintext())
    ):
        raise FinishedException


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
    return extensions.get(selection_ids.get(selection, ""))


def _selected_player_detail_action(
    extensions: PlayerDetailExtensionRegistry,
    text_value: str,
    state: T_State,
) -> str | None:
    if action := _resolve_player_detail_extension_action(extensions, text_value, state):
        return action.id
    if detail_request := resolve_player_detail_reply(
        text_value,
        selections=_stored_player_detail_selections(
            state,
            PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY,
        ),
    ):
        return detail_request.key
    return None


def _take_shared_menu_reply(
    matcher: Matcher,
    state: T_State,
) -> PlayerDetailMenuContext | None:
    if not state.get(QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY):
        return None
    context = state.get(PLAYER_DETAIL_MENU_CONTEXT_KEY)
    get_prompt_session_manager(matcher).detach_queued_conversation(state)
    return context if isinstance(context, PlayerDetailMenuContext) else None


def _configure_player_detail_state(
    features: FeatureService,
    extensions: PlayerDetailExtensionRegistry,
    event: Event,
    state: T_State,
    menu_context: PlayerDetailMenuContext,
):
    state[PLAYER_ID_KEY] = menu_context.player_id
    state[PLAYER_DETAIL_MENU_CONTEXT_KEY] = menu_context
    for detail_key in _SHORTCUT_KINDS:
        state.pop(detail_key, None)

    visible_extensions = tuple(
        action
        for action in extensions.actions()
        if event_is_feature_allowed(features, event, action.feature)
    )
    prompt_plan = plan_player_detail_prompt(
        has_collection=menu_context.has_collection,
        has_peak=menu_context.has_peak,
        has_autocard=menu_context.has_autocard,
        supports_conversation=isinstance(event, MessageEvent),
        extension_actions=visible_extensions,
    )
    state[PLAYER_DETAIL_COMMANDS_KEY] = prompt_plan.accepted_commands
    state[PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY] = prompt_plan.builtin_selections
    state[PLAYER_DETAIL_EXTENSION_SELECTIONS_KEY] = prompt_plan.extension_selections
    return prompt_plan


def _player_detail_group_reply_check(
    features: FeatureService,
    commands: tuple[str, ...],
):
    command_check = command_reply_check(commands)

    def _check(event: MessageEvent) -> bool:
        return event_is_feature_allowed(features, event, "seer_player") and (
            is_player_detail_exit(event.get_plaintext()) or command_check(event)
        )

    return _check


def _player_detail_semantic_request(
    extensions: PlayerDetailExtensionRegistry,
    features: FeatureService,
    event: MessageEvent,
    state: T_State,
) -> SemanticRequest | None:
    player_id = state.get(PLAYER_ID_KEY)
    if not isinstance(player_id, int):
        return None
    text_value = event.get_plaintext()
    extension_action = _resolve_player_detail_extension_action(
        extensions,
        text_value,
        state,
    )
    if extension_action is not None:
        if state.get(
            QUEUED_CONVERSATION_SHARED_REPLY_STATE_KEY
        ) and not event_is_feature_allowed(features, event, extension_action.feature):
            return None
        return SemanticRequest(
            action=extension_action.action,
            target=player_shortcut_semantic_request(
                kind="collection",
                player_id=player_id,
                source=SemanticRequestSource.MENU,
            ).target,
            source=SemanticRequestSource.EXTENSION,
        )

    detail_request = resolve_player_detail_reply(
        text_value,
        selections=_stored_player_detail_selections(
            state,
            PLAYER_DETAIL_BUILTIN_SELECTIONS_KEY,
        ),
    )
    if detail_request is None:
        return None
    kind = cast("PlayerShortcutKind", _SHORTCUT_KINDS[detail_request.key])
    return player_shortcut_semantic_request(
        kind=kind,
        player_id=player_id,
        source=SemanticRequestSource.MENU,
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
