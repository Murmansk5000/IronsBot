from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    PrivateMessageEvent,
)

from ironsbot.shared.messaging import event_conversation_session_id
from ironsbot.utils.matcher import prompt_session_manager, reject_with_rule

if TYPE_CHECKING:
    from nonebot.adapters import Event
    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.rule import Rule
    from nonebot.typing import T_State

    from ironsbot.shared.messaging.push_subscription_models import PushTargetType

PUSH_SUBSCRIPTION_OPTIONS_KEY = "_message_push_subscription_options"
PUSH_SUBSCRIPTION_TARGET_ID_KEY = "_message_push_subscription_target_id"
PUSH_SUBSCRIPTION_MANAGEMENT_COMMANDS = ("推送管理",)
PUSH_TIME_OPTIONS_KEY = "_message_push_time_options"
PUSH_TIME_SELECTED_KEY = "_message_push_time_selected"
PUSH_TIME_TARGET_ID_KEY = "_message_push_time_target_id"
PUSH_TIME_COMMANDS = ("推送时间", "提醒时间")


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
        version = prompt_session_manager.acquire(session_id)
        state[self.session_key] = session_id
        state[self.target_type_key] = target_type
        state[self.version_key] = version
        return session_id, version

    def rule(
        self,
        session_id: str,
        version: int,
        target_type: PushTargetType,
        *,
        selection: bool = True,
    ) -> Rule:
        event_type = (
            GroupMessageEvent if target_type == "group" else PrivateMessageEvent
        )

        def check(next_event: Event) -> bool:
            if not isinstance(next_event, event_type):
                return False
            text = next_event.get_plaintext().strip()
            return (
                event_conversation_session_id(self.namespace, next_event) == session_id
                and next_event.user_id != next_event.self_id
                and getattr(next_event, "reply", None) is None
                and (text.isdigit() if selection else bool(text))
            )

        return prompt_session_manager.make_rule(session_id, version, check)

    async def reject(
        self,
        matcher: Matcher,
        state: T_State,
        prompt: str,
        *,
        selection: bool = True,
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
        await reject_with_rule(
            matcher,
            self.rule(
                session_id,
                version,
                cast("PushTargetType", target_type),
                selection=selection,
            ),
            prompt=prompt,
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
