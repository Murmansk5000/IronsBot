from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.shared.messaging import (
    event_sender_at_user_ids,
    finish_matcher_message,
)
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)

from .matcher_rules import GROUP_ACTION_KEY, PRIVATE_ACTION_KEY

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

MESSAGE_PLUGIN_NAME = "message"


class MessagingPlugin:
    name = MESSAGE_PLUGIN_NAME
    feature = "text"
    enabled = True

    def __init__(
        self,
        *,
        private_matcher: Matcher,
        group_matcher: Matcher,
    ) -> None:
        self._private_matcher = private_matcher
        self._group_matcher = group_matcher

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        if context.action == "private_command" and isinstance(
            event,
            PrivateMessageEvent,
        ):
            await self._handle_private_command(event, context)
            return

        if context.action == "group_command" and isinstance(event, GroupMessageEvent):
            await self._handle_group_command(event, context)
            return

    async def _handle_private_command(
        self,
        event: PrivateMessageEvent,
        context: PluginContext,
    ) -> None:
        state = context.state if context.state is not None else {}
        action = state[PRIVATE_ACTION_KEY]
        await finish_matcher_message(
            context.matcher or self._private_matcher,
            action.message,
            event=event,
        )

    async def _handle_group_command(
        self,
        event: GroupMessageEvent,
        context: PluginContext,
    ) -> None:
        state = context.state if context.state is not None else {}
        action = state[GROUP_ACTION_KEY]
        at_user_ids = [
            *event_sender_at_user_ids(event),
            *action.at_user_ids,
        ]
        await finish_matcher_message(
            context.matcher or self._group_matcher,
            action.message,
            at_user_ids=at_user_ids,
            event=event,
        )


def register_messaging_plugin(
    *,
    private_matcher: Matcher,
    group_matcher: Matcher,
) -> None:
    register_plugin(
        MessagingPlugin(
            private_matcher=private_matcher,
            group_matcher=group_matcher,
        )
    )


async def dispatch_private_command(
    *,
    private_matcher: Matcher,
    event: PrivateMessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=MESSAGE_PLUGIN_NAME,
        event=event,
        matcher=private_matcher,
        state=state,
        action="private_command",
    )


async def dispatch_group_command(
    *,
    group_matcher: Matcher,
    event: GroupMessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=MESSAGE_PLUGIN_NAME,
        event=event,
        matcher=group_matcher,
        state=state,
        action="group_command",
    )


__all__ = [
    "MESSAGE_PLUGIN_NAME",
    "dispatch_group_command",
    "dispatch_private_command",
    "register_messaging_plugin",
]
