from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    PrivateMessageEvent,
)

from ironsbot.runtime.conversations import event_conversation_session_id
from ironsbot.runtime.matchers import (
    get_prompt_session_manager,
    reject_with_rule,
    update_queued_reply_check,
)
from ironsbot.runtime.message_input import is_self_command

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.rule import Rule
    from nonebot.typing import T_State

    from ironsbot.services.messaging.subscriptions import PushTargetType

PUSH_SUBSCRIPTION_OPTIONS_KEY = "_message_push_subscription_options"
PUSH_SUBSCRIPTION_PARENT_OPTION_KEY = "_message_push_subscription_parent_option"
PUSH_SUBSCRIPTION_TARGET_ID_KEY = "_message_push_subscription_target_id"
PUSH_TIME_OPTIONS_KEY = "_message_push_time_options"
PUSH_TIME_SELECTED_KEY = "_message_push_time_selected"
PUSH_TIME_TARGET_ID_KEY = "_message_push_time_target_id"


@dataclass(frozen=True, slots=True)
class PromptFlow:
    namespace: str
    session_key: str
    target_type_key: str
    version_key: str

    def begin(
        self,
        event: MessageEvent,
        state: T_State,
        target_type: PushTargetType,
    ) -> tuple[str, int]:
        session_id = event_conversation_session_id(self.namespace, event)
        version = get_prompt_session_manager(state).acquire(session_id)
        state[self.session_key] = session_id
        state[self.target_type_key] = target_type
        state[self.version_key] = version
        return session_id, version

    def rule(
        self,
        state: T_State,
        session_id: str,
        version: int,
        target_type: PushTargetType,
        *,
        selection: bool = True,
    ) -> Rule:
        return get_prompt_session_manager(state).make_rule(
            session_id,
            version,
            self.reply_check(
                session_id,
                target_type,
                selection=selection,
            ),
        )

    def reply_check(
        self,
        session_id: str,
        target_type: PushTargetType,
        *,
        selection: bool = True,
    ) -> Callable[[Event], bool]:
        event_type = (
            GroupMessageEvent if target_type == "group" else PrivateMessageEvent
        )

        def check(next_event: Event) -> bool:
            if not isinstance(next_event, event_type):
                return False
            return (
                event_conversation_session_id(self.namespace, next_event) == session_id
                and (
                    next_event.user_id != next_event.self_id
                    or is_self_command(next_event)
                )
                and getattr(next_event, "reply", None) is None
                and self.input_check(next_event, target_type, selection=selection)
            )

        return check

    def input_check(
        self,
        event: Event,
        target_type: PushTargetType,
        *,
        selection: bool = True,
    ) -> bool:
        event_type = (
            GroupMessageEvent if target_type == "group" else PrivateMessageEvent
        )
        if not isinstance(event, event_type) or (
            event.user_id == event.self_id and not is_self_command(event)
        ):
            return False
        text = event.get_plaintext().strip()
        return text.isdigit() if selection else bool(text)

    async def reject(  # noqa: PLR0913
        self,
        matcher: Matcher,
        state: T_State,
        prompt: str,
        *,
        selection: bool = True,
        replace_menu_anchor: bool = False,
        page_id: str | None = None,
    ) -> None:
        session_id = state.get(self.session_key)
        version = state.get(self.version_key)
        target_type = state.get(self.target_type_key)
        if (
            not isinstance(session_id, str)
            or not isinstance(version, int)
            or target_type not in {"private", "group"}
        ):
            await matcher.finish(prompt)
        resolved_target_type = cast("PushTargetType", target_type)
        reply_check = self.reply_check(
            session_id,
            resolved_target_type,
            selection=selection,
        )
        update_queued_reply_check(
            matcher,
            reply_check,
            group_reply_check=lambda next_event: self.input_check(
                next_event,
                resolved_target_type,
                selection=selection,
            ),
        )
        await reject_with_rule(
            matcher,
            self.rule(
                state,
                session_id,
                version,
                resolved_target_type,
                selection=selection,
            ),
            prompt=prompt,
            replace_menu_anchor=replace_menu_anchor,
            page_id=page_id,
        )


PUSH_SUBSCRIPTION_FLOW = PromptFlow(
    "message_push_subscription",
    "_message_push_subscription_session",
    "_message_push_subscription_target_type",
    "_message_push_subscription_version",
)
PUSH_TIME_FLOW = PromptFlow(
    "message_push_time",
    "_message_push_time_session",
    "_message_push_time_target_type",
    "_message_push_time_version",
)
