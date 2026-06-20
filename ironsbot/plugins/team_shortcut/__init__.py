import asyncio

from nonebot import on_message
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.plugins.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.shared.messaging import finish_message_sequence
from ironsbot.plugins.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.shared.features import is_group_feature_allowed
from ironsbot.shared.messaging.text import build_message, command_text_matches
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .adapter import fetch_team_shortcut_result
from .config import (
    Config,
    get_team_ids,
    get_team_resource_users,
    get_team_shortcut_config,
)

TEAM_SHORTCUT_PLUGIN_NAME = "team_shortcut"

__plugin_meta__ = PluginMetadata(
    name="战队快捷",
    description="在配置群里用短指令查询固定战队",
    usage=(
        "【战队快捷】\n"
        "群聊发送 seer.team_shortcut.commands 中配置的指令，默认：战队。\n"
        "机器人会查询 seer.team_shortcut.team_ids 中配置的战队；"
        "战队资源低于 seer.team_shortcut.resource_threshold 时可 "
        "@ seer.team_shortcut.resource_users。"
    ),
    config=Config,
)


def _build_resource_notice() -> Message:
    config = get_team_shortcut_config()
    return build_message(
        config.resource_message,
        at_user_ids=get_team_resource_users(),
    )


async def _is_team_shortcut(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    if not get_team_ids():
        return False

    if not is_group_feature_allowed(
        event.user_id,
        event.group_id,
        "team",
    ):
        return False

    return command_text_matches(
        event.get_plaintext(),
        get_team_shortcut_config().commands,
    )


team_shortcut_matcher = on_message(
    rule=Rule(_is_team_shortcut) & no_reply(),
    priority=2,
    block=True,
)


class TeamShortcutPlugin:
    name = TEAM_SHORTCUT_PLUGIN_NAME
    feature = "team"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        matcher = context.matcher or team_shortcut_matcher
        replies: list[Message] = []
        resource_notice_needed = False

        config = get_team_shortcut_config()
        for team_id in get_team_ids():
            try:
                result = await asyncio.wait_for(
                    fetch_team_shortcut_result(team_id),
                    timeout=config.query_timeout_seconds,
                )
                await mark_headless_available(source="战队快捷")
            except FinishedException:
                raise
            except (NotLoggedInError, DisconnectedError) as e:
                await mark_headless_unavailable(str(e), source="战队快捷")
                replies.append(
                    Message(
                        f"战队 {team_id} 暂时查不了："
                        "需要连接赛尔号游戏服务器，当前可能在维护、未开放或无头客户端未登录。"
                    )
                )
                continue
            except TimeoutError:
                replies.append(Message(f"战队 {team_id} 查询超时，请稍后再试。"))
                continue
            except Exception as e:  # noqa: BLE001
                logger.exception(f"team shortcut query failed, team id {team_id}: {e}")
                replies.append(Message(f"战队 {team_id} 查询失败，请稍后再试。"))
                continue

            replies.append(Message(result.message))
            if result.resource < config.resource_threshold:
                resource_notice_needed = True

        if not replies:
            return

        if resource_notice_needed:
            replies.append(_build_resource_notice())

        await finish_message_sequence(matcher, replies, event=event)


register_plugin(TeamShortcutPlugin())


@team_shortcut_matcher.handle()
async def handle_team_shortcut(matcher: Matcher, event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=TEAM_SHORTCUT_PLUGIN_NAME,
        event=event,
        matcher=matcher,
    )
