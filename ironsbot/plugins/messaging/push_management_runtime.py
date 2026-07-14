from __future__ import annotations

from typing import TYPE_CHECKING, cast

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    PrivateMessageEvent,
)

from ironsbot.shared.messaging import event_conversation_session_id
from ironsbot.shared.messaging.push_subscription_store import PushUnsubscribeStore
from ironsbot.utils.matcher import prompt_session_manager, reject_with_rule

from .config import get_message_config
from .push_subscription import (
    build_messaging_push_subscription_menu_prompt,
    build_messaging_push_subscription_options,
)
from .push_time import (
    PushTimeOption,
    build_push_time_menu_prompt,
    build_push_time_options,
    normalize_push_time_input,
    push_time_value_prompt,
)

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.matcher import Matcher
    from nonebot.rule import Rule
    from nonebot.typing import T_State

    from ironsbot.shared.messaging.push_subscription_models import (
        PushSubscriptionOption,
        PushTargetType,
    )

PUSH_SUBSCRIPTION_OPTIONS_KEY = "_message_push_subscription_options"
PUSH_SUBSCRIPTION_SESSION_KEY = "_message_push_subscription_session"
PUSH_SUBSCRIPTION_TARGET_ID_KEY = "_message_push_subscription_target_id"
PUSH_SUBSCRIPTION_TARGET_TYPE_KEY = "_message_push_subscription_target_type"
PUSH_SUBSCRIPTION_VERSION_KEY = "_message_push_subscription_version"
PUSH_SUBSCRIPTION_NAMESPACE = "message_push_subscription"
PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS = ("推送管理",)
PUSH_TIME_OPTIONS_KEY = "_message_push_time_options"
PUSH_TIME_SELECTED_KEY = "_message_push_time_selected"
PUSH_TIME_SESSION_KEY = "_message_push_time_session"
PUSH_TIME_TARGET_ID_KEY = "_message_push_time_target_id"
PUSH_TIME_TARGET_TYPE_KEY = "_message_push_time_target_type"
PUSH_TIME_VERSION_KEY = "_message_push_time_version"
PUSH_TIME_NAMESPACE = "message_push_time"
PUSH_TIME_COMMANDS = ("推送时间", "提醒时间")


def _push_subscription_store() -> PushUnsubscribeStore:
    return PushUnsubscribeStore(get_message_config().push_unsubscribe.data_path)


def _push_subscription_options(
    target_type: PushTargetType,
    target_id: int,
) -> list[PushSubscriptionOption]:
    return build_messaging_push_subscription_options(
        target_type,
        target_id,
        store=_push_subscription_store(),
    )


def _push_subscription_menu_prompt(
    target_type: PushTargetType,
    options: list[PushSubscriptionOption],
    *,
    read_only: bool = False,
) -> str:
    return build_messaging_push_subscription_menu_prompt(
        target_type,
        options,
        read_only=read_only,
    )


def _push_time_options(
    target_type: PushTargetType,
    target_id: int,
) -> list[PushTimeOption]:
    return build_push_time_options(
        target_type,
        target_id,
        store=_push_subscription_store(),
    )


def _push_time_menu_prompt(
    target_type: PushTargetType,
    options: list[PushTimeOption],
) -> str:
    return build_push_time_menu_prompt(target_type, options)


def _push_subscription_selection_rule(
    session_id: str,
    version: int,
    target_type: PushTargetType,
) -> Rule:
    event_type = GroupMessageEvent if target_type == "group" else PrivateMessageEvent

    def _check(next_event: Event) -> bool:
        if not isinstance(next_event, event_type):
            return False
        if (
            event_conversation_session_id(
                PUSH_SUBSCRIPTION_NAMESPACE,
                next_event,
            )
            != session_id
        ):
            return False
        if next_event.user_id == next_event.self_id:
            return False
        if getattr(next_event, "reply", None) is not None:
            return False
        return next_event.get_plaintext().strip().isdigit()

    return prompt_session_manager.make_rule(session_id, version, _check)


def _push_time_selection_rule(
    session_id: str,
    version: int,
    target_type: PushTargetType,
) -> Rule:
    event_type = GroupMessageEvent if target_type == "group" else PrivateMessageEvent

    def _check(next_event: Event) -> bool:
        if not isinstance(next_event, event_type):
            return False
        if event_conversation_session_id(PUSH_TIME_NAMESPACE, next_event) != session_id:
            return False
        if next_event.user_id == next_event.self_id:
            return False
        if getattr(next_event, "reply", None) is not None:
            return False
        return next_event.get_plaintext().strip().isdigit()

    return prompt_session_manager.make_rule(session_id, version, _check)


def _push_time_input_rule(
    session_id: str,
    version: int,
    target_type: PushTargetType,
) -> Rule:
    event_type = GroupMessageEvent if target_type == "group" else PrivateMessageEvent

    def _check(next_event: Event) -> bool:
        if not isinstance(next_event, event_type):
            return False
        if event_conversation_session_id(PUSH_TIME_NAMESPACE, next_event) != session_id:
            return False
        if next_event.user_id == next_event.self_id:
            return False
        if getattr(next_event, "reply", None) is not None:
            return False
        return bool(next_event.get_plaintext().strip())

    return prompt_session_manager.make_rule(session_id, version, _check)


async def _reject_push_subscription_selection(
    matcher: Matcher,
    state: T_State,
    prompt: str,
) -> None:
    session_id = state.get(PUSH_SUBSCRIPTION_SESSION_KEY)
    version = state.get(PUSH_SUBSCRIPTION_VERSION_KEY)
    target_type = state.get(PUSH_SUBSCRIPTION_TARGET_TYPE_KEY)
    if (
        not isinstance(session_id, str)
        or not isinstance(version, int)
        or target_type not in {"private", "group"}
    ):
        await matcher.finish(prompt)
    target_type = cast("PushTargetType", target_type)

    await reject_with_rule(
        matcher,
        _push_subscription_selection_rule(
            session_id,
            version,
            target_type,
        ),
        prompt=prompt,
    )


async def _reject_push_time_selection(
    matcher: Matcher,
    state: T_State,
    prompt: str,
) -> None:
    session_id = state.get(PUSH_TIME_SESSION_KEY)
    version = state.get(PUSH_TIME_VERSION_KEY)
    target_type = state.get(PUSH_TIME_TARGET_TYPE_KEY)
    if (
        not isinstance(session_id, str)
        or not isinstance(version, int)
        or target_type not in {"private", "group"}
    ):
        await matcher.finish(prompt)
    target_type = cast("PushTargetType", target_type)

    await reject_with_rule(
        matcher,
        _push_time_selection_rule(session_id, version, target_type),
        prompt=prompt,
    )


async def _reject_push_time_input(
    matcher: Matcher,
    state: T_State,
    prompt: str,
) -> None:
    session_id = state.get(PUSH_TIME_SESSION_KEY)
    version = state.get(PUSH_TIME_VERSION_KEY)
    target_type = state.get(PUSH_TIME_TARGET_TYPE_KEY)
    if (
        not isinstance(session_id, str)
        or not isinstance(version, int)
        or target_type not in {"private", "group"}
    ):
        await matcher.finish(prompt)
    target_type = cast("PushTargetType", target_type)

    await reject_with_rule(
        matcher,
        _push_time_input_rule(session_id, version, target_type),
        prompt=prompt,
    )


def _push_time_value_prompt(option: PushTimeOption) -> str:
    return push_time_value_prompt(option)


def _normalize_push_time_input(option: PushTimeOption, text: str) -> str | None:
    return normalize_push_time_input(option, text)
