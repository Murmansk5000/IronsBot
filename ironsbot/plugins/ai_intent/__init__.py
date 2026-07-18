from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.config.models.ai import AiIntentAction
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.services.ai.intent_actions import (
    classify_ai_intent_action,
    is_team_action,
    run_ai_reply_action,
)
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    finish_event_reply,
)
from ironsbot.utils.rule import no_reply

from .team_actions import run_team_action

ACTION_KEY = "_ai_intent_action"


async def _match_ai_intent_action(event: MessageEvent, state: T_State) -> bool:
    action = await classify_ai_intent_action(event)
    if action is None:
        return False

    state[ACTION_KEY] = action
    return True


async def _handle_ai_reply_action(
    action: AiIntentAction,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    reply = await run_ai_reply_action(action, event)
    if reply is None:
        return

    await finish_event_reply(
        matcher,
        event,
        reply,
        mention_sender=True,
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
    headless: HeadlessService,
    team_resource_timeout_seconds: float,
) -> None:
    async def handle_action(
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        action = state[ACTION_KEY]
        if is_team_action(action):
            await run_team_action(
                matcher,
                event,
                action,
                headless.get_game(),
                team_resource_timeout_seconds,
            )
            return
        if action.action == "ai_reply":
            await _handle_ai_reply_action(action, matcher, event)
            return
        await finish_event_reply(
            matcher,
            event,
            action.message,
            mention_sender=True,
        )

    matcher = registry.on_message(
        policy=CommandPolicy.command(_resolve_action_command_id),
        rule=Rule(_match_ai_intent_action) & no_reply(),
        priority=get_matcher_priority("ai_intent", 4),
        block=True,
    )
    matcher.append_handler(handle_action)
