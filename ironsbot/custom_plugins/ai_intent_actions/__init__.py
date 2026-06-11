import asyncio
import re

from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.ai_chat.client import call_ai_chat
from ironsbot.custom_plugins.ai_chat.constants import (
    EMPTY_REPLY,
    REQUEST_FAILED_REPLY,
)
from ironsbot.custom_plugins.message_actions import (
    build_message,
    finish_event_reply,
    finish_message_sequence,
)
from ironsbot.custom_plugins.team_shortcut.adapter import fetch_team_shortcut_result
from ironsbot.shared.features import (
    is_group_feature_allowed,
    is_private_feature_allowed,
)
from ironsbot.shared.messaging.text import command_text_matches, normalize_command_text
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .config import (
    AiIntentAction,
    Config,
    get_ai_config,
    get_ai_key,
    get_configured_actions,
    get_team_ids,
    get_team_resource_users,
    get_team_shortcut_config,
)

ACTION_KEY = "_ai_intent_action"
AI_INTENT_PLUGIN_NAME = "ai_intent"


class _TemplateContext(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"

__plugin_meta__ = PluginMetadata(
    name="AI意图动作",
    description="用关键词粗筛消息，再让 AI 判断意图并触发配置动作。",
    usage=(
        "【AI意图动作】\n"
        "默认规则：消息包含“战队”时，请 AI 判断发送者是否想加入战队。\n"
        "若判断为是，则发送 5 级战队审核群链接。\n"
        "可通过 ai.intent_actions 配置更多关键词、判定意图和动作。"
    ),
    config=Config,
)


def _contains_any_keyword(text: str, keywords: list[str]) -> bool:
    normalized = normalize_command_text(text)
    return any(
        normalize_command_text(keyword) in normalized
        for keyword in keywords
    )


def _excluded_by_command(text: str, action: AiIntentAction) -> bool:
    exclude_commands = list(action.exclude_commands)
    if action.action == "team_shortcut":
        exclude_commands.extend(get_team_shortcut_config().commands)

    return bool(exclude_commands) and command_text_matches(text, exclude_commands)


def _is_action_allowed(event: MessageEvent, action: AiIntentAction) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_feature_allowed(
            event.user_id,
            event.group_id,
            action.feature,
        )

    return is_private_feature_allowed(event.user_id, action.feature)


def _format_action_template(action: AiIntentAction, template: str, text: str) -> str:
    return template.format_map(
        _TemplateContext(
            action_id=action.id or action.template or "unnamed",
            feature=action.feature,
            intent=action.intent,
            keywords=", ".join(action.keywords),
            message=text,
        )
    )


def _build_intent_prompt(action: AiIntentAction, text: str) -> str:
    return _format_action_template(action, action.classifier_prompt, text)


def _reply_is_yes(reply: str) -> bool:
    normalized = reply.strip().lower()
    first_line = re.sub(
        r"^[\s.\u3002:\uff1a,\uff0c\"'`]+|"
        r"[\s.\u3002:\uff1a,\uff0c\"'`]+$",
        "",
        normalized.splitlines()[0],
    )
    return first_line in {
        "yes",
        "y",
        "true",
        "\u662f",
        "\u5bf9",
        "\u7b26\u5408",
    }


async def _match_ai_intent_action(event: MessageEvent, state: T_State) -> bool:
    if not get_ai_config().intent_actions_enabled:
        return False

    text = event.get_plaintext().strip()
    if not text or not get_ai_key():
        return False

    for action in get_configured_actions():
        if (
            not action.enabled
            or not _is_action_allowed(event, action)
            or not _contains_any_keyword(text, action.keywords)
            or _excluded_by_command(text, action)
        ):
            continue

        try:
            reply = await call_ai_chat(_build_intent_prompt(action, text), [])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"AI intent action failed to classify {action.id}: {e}")
            return False

        if reply in {REQUEST_FAILED_REPLY, EMPTY_REPLY}:
            return False

        logger.info(
            f"AI intent action {action.id or '<unnamed>'} classified "
            f"{event.user_id}: {reply!r}"
        )
        if _reply_is_yes(reply):
            state[ACTION_KEY] = action
            return True

    return False


ai_intent_action_matcher = on_message(
    rule=Rule(_match_ai_intent_action) & no_reply(),
    priority=4,
    block=True,
)


def _build_resource_notice() -> Message:
    config = get_team_shortcut_config()
    return build_message(
        config.resource_message,
        at_user_ids=get_team_resource_users(),
    )


async def _handle_team_shortcut_action(
    action: AiIntentAction,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    team_ids = action.team_ids or get_team_ids()
    if not team_ids:
        await finish_event_reply(
            matcher,
            event,
            "战队信息还没有配置 seer.team_shortcut.team_ids。",
            mention_sender=True,
        )

    replies: list[Message] = []
    resource_notice_needed = False
    for team_id in team_ids:
        try:
            result = await asyncio.wait_for(
                fetch_team_shortcut_result(team_id),
                timeout=get_team_shortcut_config().query_timeout_seconds,
            )
        except FinishedException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(
                f"AI intent team action query failed, team id {team_id}: {e}"
            )
            replies.append(Message(f"战队 {team_id} 查询失败，请稍后再试。"))
            continue

        replies.append(Message(result.message))
        if result.resource < get_team_shortcut_config().resource_threshold:
            resource_notice_needed = True

    if not replies:
        return

    if action.include_team_resource_notice and resource_notice_needed:
        replies.append(_build_resource_notice())

    await finish_message_sequence(matcher, replies, event=event)


async def _handle_ai_reply_action(
    action: AiIntentAction,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    prompt = _format_action_template(
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

        if action.action == "team_shortcut":
            await _handle_team_shortcut_action(action, matcher, event)
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
