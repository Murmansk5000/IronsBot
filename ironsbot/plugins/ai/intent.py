from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.rule import Rule

from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.runtime.onebot_context import build_notice_source
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import no_reply

from .team_actions import run_team_action

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nonebot.adapters.onebot.v11 import MessageEvent
    from nonebot.matcher import Matcher
    from nonebot.typing import T_State

    from ironsbot.core.messaging import AiIntentAction
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.team.resource import TeamResourceService

ACTION_KEY = "_ai_intent_action"
ACTION_SOURCE_CONTEXT_KEY = "_ai_intent_source_context"


async def _handle_ai_reply_action(
    service: AiService,
    action: AiIntentAction,
    matcher: Matcher,
    event: MessageEvent,
    source_context: str | None,
) -> None:
    reply = await service.run_reply_action(
        action,
        event.get_plaintext(),
        source_context=source_context,
    )
    if reply is None:
        return

    await finish_event_reply(
        matcher,
        event,
        reply,
    )


def _resolve_action_command_id(
    _event: MessageEvent,
    state: T_State,
) -> str:
    action = state.get(ACTION_KEY)
    action_id = str(getattr(action, "id", "")).strip()
    return f"ai_intent.{action_id}" if action_id else "ai_intent"


def install(
    registry: MatcherRegistry,
    service: AiService,
    group_aliases: Mapping[str, int],
    team_resource: TeamResourceService,
) -> None:
    async def match_action(event: MessageEvent, state: T_State) -> bool:
        text = event.get_plaintext().strip()
        group_id = getattr(event, "group_id", None)
        source_context = await build_notice_source(
            event,
            text,
            group_aliases,
        )
        action = await service.classify_intent(
            text,
            user_id=int(event.user_id),
            group_id=int(group_id) if group_id is not None else None,
            source_context=source_context,
        )
        if action is None:
            return False
        state[ACTION_KEY] = action
        state[ACTION_SOURCE_CONTEXT_KEY] = source_context
        return True

    async def handle_action(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        action = state[ACTION_KEY]
        if service.is_team_action(action):
            await run_team_action(
                matcher,
                event,
                action,
                team_resource,
            )
            return
        if action.action == "ai_reply":
            await _handle_ai_reply_action(
                service,
                action,
                matcher,
                event,
                str(state.get(ACTION_SOURCE_CONTEXT_KEY, "") or "") or None,
            )
            return
        await finish_event_reply(
            matcher,
            event,
            action.message,
        )

    matcher = registry.on_message(
        policy=CommandPolicy.command(_resolve_action_command_id),
        rule=Rule(match_action) & no_reply(),
        priority=registry.priority("ai_intent"),
        block=True,
    )
    matcher.append_handler(handle_action)
