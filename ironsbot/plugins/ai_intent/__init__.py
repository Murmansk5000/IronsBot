from typing import Any

from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.config.models.ai import AiIntentAction
from ironsbot.config.models.app import AppConfig
from ironsbot.services.ai.intent_actions import (
    classify_ai_intent_action,
    is_team_action,
    run_ai_reply_action,
)
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    finish_event_reply,
)
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

ACTION_KEY = "_ai_intent_action"
AI_INTENT_PLUGIN_NAME = "ai_intent"
TEAM_RECOMMEND_PLUGIN_NAME = "team_recommend"


__plugin_meta__ = PluginMetadata(
    name="AI意图分析",
    description="按配置识别简短意图，并触发对应回复或功能。",
    usage=(
        "【AI意图分析】\n"
        "按 ai.intent_actions 配置进行关键词粗筛和意图判断。\n"
        "命中后可发送固定消息、生成 AI 回复，或分发给其它功能处理。\n"
        "具体触发词、判定提示和动作都以当前配置为准。"
    ),
    config=AppConfig,
)


async def _match_ai_intent_action(event: MessageEvent, state: T_State) -> bool:
    action = await classify_ai_intent_action(event)
    if action is None:
        return False

    state[ACTION_KEY] = action
    return True


ai_intent_action_matcher = on_message(
    rule=Rule(_match_ai_intent_action) & no_reply(),
    priority=get_matcher_priority("ai_intent", 4),
    block=True,
)


async def _handle_ai_reply_action(
    action: AiIntentAction,
    matcher: Any,
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


@ai_intent_action_matcher.handle()
async def handle_ai_intent_action(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=AI_INTENT_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
    )


class AiIntentPlugin:
    name = AI_INTENT_PLUGIN_NAME
    feature = "ai_intent"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        state = context.state if context.state is not None else {}
        action = state[ACTION_KEY]
        matcher = context.matcher or ai_intent_action_matcher

        if is_team_action(action):
            await dispatch_plugin(
                plugin_name=TEAM_RECOMMEND_PLUGIN_NAME,
                event=event,
                matcher=matcher,
                action=action.action,
                ai_action=action,
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


register_plugin(AiIntentPlugin())
