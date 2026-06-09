from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.custom_plugins.feature_policy import is_group_feature_allowed
from ironsbot.custom_plugins.message_actions import (
    build_message,
    command_text_matches,
    finish_message_sequence,
)
from ironsbot.utils.rule import no_reply

from .adapter import fetch_team_shortcut_result
from .config import plugin_config

RESOURCE_NOTICE_THRESHOLD = 1000

__plugin_meta__ = PluginMetadata(
    name="战队快捷",
    description="在配置群里用短指令查询固定战队",
    usage=(
        "【战队快捷】\n"
        "群聊发送 TEAM_COMMANDS 中配置的指令，默认：战队。\n"
        "机器人会查询 TEAM_IDS 中配置的战队；"
        "战队资源低于 1000 时可 @ TEAM_RESOURCE_USERS。"
    ),
)


def _build_resource_notice() -> Message:
    return build_message(
        plugin_config.team_resource_message,
        at_user_ids=plugin_config.team_resource_users,
    )


async def _is_team_shortcut(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    if not plugin_config.team_ids:
        return False

    if not is_group_feature_allowed(
        event.user_id,
        event.group_id,
        "team",
    ):
        return False

    return command_text_matches(
        event.get_plaintext(),
        plugin_config.team_commands,
    )


team_shortcut_matcher = on_message(
    rule=Rule(_is_team_shortcut) & no_reply(),
    priority=2,
    block=True,
)


@team_shortcut_matcher.handle()
async def handle_team_shortcut(matcher: Matcher, event: MessageEvent) -> None:
    replies: list[Message] = []
    resource_notice_needed = False

    for team_id in plugin_config.team_ids:
        try:
            result = await fetch_team_shortcut_result(team_id)
        except FinishedException:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception(f"team shortcut query failed, team id {team_id}: {e}")
            replies.append(Message(f"战队 {team_id} 查询失败，请稍后再试。"))
            continue

        replies.append(Message(result.message))
        if result.resource < RESOURCE_NOTICE_THRESHOLD:
            resource_notice_needed = True

    if not replies:
        return

    if resource_notice_needed:
        replies.append(_build_resource_notice())

    await finish_message_sequence(matcher, replies, event=event)
