import asyncio

from nonebot import on_message, require
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule

from ironsbot.utils.rule import no_reply

require("ironsbot.plugins.get_seer_info")

from ironsbot.plugins.get_seer_info.commands.team import _format_team_info
from ironsbot.plugins.get_seer_info.depends import GameClient
from ironsbot.plugins.headless_seer.game import SeerGame

from .config import plugin_config


def _build_resource_notice() -> Message:
    message = Message()
    for user_id in plugin_config.team_shortcut_resource_notice_user_ids:
        message += MessageSegment.at(user_id)
        message += MessageSegment.text(" ")
    message += MessageSegment.text(plugin_config.team_shortcut_resource_notice_message)
    return message


async def _is_team_shortcut(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    if not plugin_config.team_shortcut_group_ids:
        return False

    if not plugin_config.team_shortcut_team_ids:
        return False

    if event.group_id not in plugin_config.team_shortcut_group_ids:
        return False

    return event.get_plaintext().strip() in plugin_config.team_shortcut_commands


team_shortcut_matcher = on_message(
    rule=Rule(_is_team_shortcut) & no_reply(),
    priority=2,
    block=True,
)


@team_shortcut_matcher.handle()
async def handle_team_shortcut(
    matcher: Matcher,
    game: SeerGame = GameClient,
) -> None:
    replies: list[Message] = []
    resource_notice_needed = False

    for team_id in plugin_config.team_shortcut_team_ids:
        try:
            team_info = await game.get_team_info(team_id)
        except FinishedException:
            raise
        except Exception as e:
            logger.exception(f"快捷战队查询失败，战队ID: {team_id}: {e}")
            replies.append(Message(f"战队 {team_id} 查询失败，请稍后再试。"))
            continue

        replies.append(Message(_format_team_info(team_info)))
        if team_info.score < 1000:
            resource_notice_needed = True

    if not replies:
        return

    if resource_notice_needed:
        replies.append(_build_resource_notice())

    for reply in replies[:-1]:
        await matcher.send(reply)
        await asyncio.sleep(0.5)

    await matcher.finish(replies[-1])
