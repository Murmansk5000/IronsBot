from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.ai_chat.client import (
    EMPTY_REPLY,
    REQUEST_FAILED_REPLY,
    call_ai_chat,
)
from ironsbot.custom_plugins.ai_chat.config import plugin_config as ai_config
from ironsbot.custom_plugins.message_actions import (
    build_message,
    command_text_matches,
    finish_event_reply,
    finish_message_sequence,
    normalize_command_text,
)
from ironsbot.custom_plugins.superuser_policy import (
    is_group_allowed_for_user,
    is_private_user_allowed,
)
from ironsbot.custom_plugins.team_shortcut.adapter import fetch_team_shortcut_result
from ironsbot.custom_plugins.team_shortcut.config import plugin_config as team_config
from ironsbot.utils.rule import no_reply

from .config import AiIntentAction, Config, plugin_config

ACTION_KEY = "_ai_intent_action"
TEAM_RESOURCE_NOTICE_THRESHOLD = 1000

__plugin_meta__ = PluginMetadata(
    name="AI意图动作",
    description="用关键词粗筛消息，再让 AI 判断意图并触发配置动作。",
    usage=(
        "【AI意图动作】\n"
        "默认规则：消息包含“战队”时，请 AI 判断发送者是否想加入战队。\n"
        "若判断为是，则发送 TEAM_IDS 配置的战队信息。\n"
        "可通过 AI_INTENT_ACTIONS 配置更多关键词、判定意图和动作。"
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
        exclude_commands.extend(team_config.team_commands)

    return bool(exclude_commands) and command_text_matches(text, exclude_commands)


def _is_action_allowed(event: MessageEvent, action: AiIntentAction) -> bool:
    if isinstance(event, GroupMessageEvent):
        group_ids = action.group_ids or (
            team_config.team_groups
            if action.action == "team_shortcut"
            else []
        )
        return is_group_allowed_for_user(event.user_id, event.group_id, group_ids)

    return is_private_user_allowed(event.user_id, action.user_ids)


def _build_intent_prompt(action: AiIntentAction, text: str) -> str:
    return (
        "You are a strict intent classifier for a QQ bot.\n"
        "Only output one word: yes or no.\n"
        f"Intent definition: {action.intent}\n"
        f"Message: {text}\n"
        "Does the message match the intent?"
    )


def _reply_is_yes(reply: str) -> bool:
    normalized = reply.strip().lower()
    first_line = normalized.splitlines()[0].strip(" .。!！,，:：;；\"'`")
    return first_line in {"yes", "y", "true", "是", "对", "符合"}


async def _match_ai_intent_action(event: MessageEvent, state: T_State) -> bool:
    if not plugin_config.ai_intent_actions_enabled:
        return False

    text = event.get_plaintext().strip()
    if not text or not ai_config.ai_key:
        return False

    for action in plugin_config.ai_intent_actions:
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
    return build_message(
        team_config.team_resource_message,
        at_user_ids=team_config.team_resource_users,
    )


async def _handle_team_shortcut_action(
    action: AiIntentAction,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    team_ids = action.team_ids or team_config.team_ids
    if not team_ids:
        await finish_event_reply(
            matcher,
            event,
            "战队信息还没有配置 TEAM_IDS。",
            mention_sender=True,
        )

    replies: list[Message] = []
    resource_notice_needed = False
    for team_id in team_ids:
        try:
            result = await fetch_team_shortcut_result(team_id)
        except FinishedException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(
                f"AI intent team action query failed, team id {team_id}: {e}"
            )
            replies.append(Message(f"战队 {team_id} 查询失败，请稍后再试。"))
            continue

        replies.append(Message(result.message))
        if result.resource < TEAM_RESOURCE_NOTICE_THRESHOLD:
            resource_notice_needed = True

    if not replies:
        return

    if action.include_team_resource_notice and resource_notice_needed:
        replies.append(_build_resource_notice())

    await finish_message_sequence(matcher, replies, event=event)


@ai_intent_action_matcher.handle()
async def handle_ai_intent_action(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    action = state[ACTION_KEY]

    if action.action == "team_shortcut":
        await _handle_team_shortcut_action(action, matcher, event)
        return

    await finish_event_reply(
        matcher,
        event,
        action.message,
        mention_sender=True,
    )
