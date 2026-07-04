from nonebot import on_message
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.services.ai.client import call_ai_chat, get_ai_key
from ironsbot.services.ai.constants import (
    EMPTY_REPLY,
    REQUEST_FAILED_REPLY,
)
from ironsbot.services.ai.intent import (
    AiIntentAction,
    build_intent_prompt,
    contains_any_keyword,
    excluded_by_command,
    excluded_by_context,
    format_action_template,
    get_ai_intent_config,
    get_configured_actions,
    is_action_allowed,
    passes_action_prefilter,
    reply_is_yes,
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

from .config import Config

ACTION_KEY = "_ai_intent_action"
AI_INTENT_PLUGIN_NAME = "ai_intent"
TEAM_RECOMMEND_PLUGIN_NAME = "team_recommend"
TEAM_ACTIONS = {"team_recommend", "team_resource"}


__plugin_meta__ = PluginMetadata(
    name="AI意图分析",
    description="按配置识别简短意图，并触发对应回复或功能。",
    usage=(
        "【AI意图分析】\n"
        "按 ai.intent_actions 配置进行关键词粗筛和意图判断。\n"
        "命中后可发送固定消息、生成 AI 回复，或分发给其它功能处理。\n"
        "具体触发词、判定提示和动作都以当前配置为准。"
    ),
    config=Config,
)


async def _match_ai_intent_action(event: MessageEvent, state: T_State) -> bool:
    if not get_ai_intent_config().intent_actions_enabled:
        return False

    text = event.get_plaintext().strip()
    if not text or not get_ai_key():
        return False

    for action in get_configured_actions():
        if (
            not action.enabled
            or not is_action_allowed(event, action)
            or not contains_any_keyword(text, action.keywords)
            or not passes_action_prefilter(text, action)
            or excluded_by_command(text, action)
            or excluded_by_context(text, action)
        ):
            continue

        try:
            reply = await call_ai_chat(build_intent_prompt(action, text), [])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AI intent action failed to classify {action.id}: {e}")
            return False

        if reply in {REQUEST_FAILED_REPLY, EMPTY_REPLY}:
            return False

        logger.info(
            f"AI intent action {action.id or '<unnamed>'} classified "
            f"{event.user_id}: {reply!r}"
        )
        if reply_is_yes(reply):
            state[ACTION_KEY] = action
            return True

    return False


ai_intent_action_matcher = on_message(
    rule=Rule(_match_ai_intent_action) & no_reply(),
    priority=get_matcher_priority("ai_intent", 4),
    block=True,
)


async def _handle_ai_reply_action(
    action: AiIntentAction,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    prompt = format_action_template(
        action,
        action.reply_prompt,
        event.get_plaintext().strip(),
    )
    reply = await call_ai_chat(prompt, [])
    if reply in {REQUEST_FAILED_REPLY, EMPTY_REPLY}:
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

        if action.action in TEAM_ACTIONS:
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
