import asyncio

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.plugin import PluginMetadata
from nonebot.rule import Rule

from ironsbot.config.models.app import AppConfig
from ironsbot.config.models.seer import TeamResourceSubscriptionConfig
from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.services.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.services.team_resource_adapter import (
    TeamResourceResult,
    fetch_team_resource_result,
)
from ironsbot.shared.command_text import command_text_matches
from ironsbot.shared.features import group_has_feature, is_group_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import finish_message_sequence
from ironsbot.shared.messaging.text import build_message
from ironsbot.utils.rule import no_reply

from .config import (
    at_users_for_subscription,
    get_team_resource_config,
    resolve_group_id,
    subscriptions_for_group,
)

TEAM_RESOURCE_FEATURE = "team_resource_subscription"

__plugin_meta__ = PluginMetadata(
    name="战队资源订阅",
    description="订阅群内固定战队，并在资源不足时定时提醒指定用户。",
    usage=(
        "【战队资源订阅】\n"
        "群聊发送 seer.team_resource.commands 中配置的指令，默认：战队。\n"
        "机器人会查询本群 seer.team_resource.subscriptions 中订阅的战队。\n"
        "到达 seer.team_resource.times 配置时间后，"
        "资源低于订阅阈值的战队会提醒指定用户。"
    ),
    config=AppConfig,
)


def _format_resource_notice(
    result: TeamResourceResult,
    subscription: TeamResourceSubscriptionConfig,
) -> Message:
    config = get_team_resource_config()
    line = config.resource_line.format(
        team_name=result.team_name,
        team_id=result.team_id,
        resource=result.resource,
        threshold=subscription.threshold,
    )
    text = f"{line}\n{config.resource_message}"
    return build_message(
        text,
        at_user_ids=at_users_for_subscription(subscription),
    )


async def _fetch_team_result(team_id: int, *, source: str) -> TeamResourceResult:
    result = await fetch_team_resource_result(team_id)
    await mark_headless_available(source=source)
    return result


async def _fetch_team_result_for_manual(team_id: int) -> TeamResourceResult | Message:
    try:
        return await asyncio.wait_for(
            _fetch_team_result(team_id, source="战队资源订阅"),
            timeout=get_team_resource_config().query_timeout_seconds,
        )
    except FinishedException:
        raise
    except (NotLoggedInError, DisconnectedError) as e:
        await mark_headless_unavailable(str(e), source="战队资源订阅")
        return Message(
            f"战队 {team_id} 暂时查不了："
            "需要连接赛尔号游戏服务器，当前可能在维护、未开放或无头客户端未登录。"
        )
    except TimeoutError:
        return Message(f"战队 {team_id} 查询超时，请稍后再试。")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"team resource query failed, team id {team_id}: {e}")
        return Message(f"战队 {team_id} 查询失败，请稍后再试。")


def _team_ids_for_manual_query(
    subscriptions: list[TeamResourceSubscriptionConfig],
) -> list[int]:
    seen: set[int] = set()
    team_ids: list[int] = []
    for subscription in subscriptions:
        for team_id in subscription.team_ids:
            if team_id in seen:
                continue
            seen.add(team_id)
            team_ids.append(team_id)
    return team_ids


async def _is_team_resource_query(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    config = get_team_resource_config()
    if not config.enabled or not subscriptions_for_group(event.group_id):
        return False

    if not is_group_feature_allowed(
        event.user_id,
        event.group_id,
        TEAM_RESOURCE_FEATURE,
    ):
        return False

    return command_text_matches(event.get_plaintext(), config.commands)


team_resource_matcher = on_message(
    rule=Rule(_is_team_resource_query) & no_reply(),
    priority=get_matcher_priority("team_resource_subscription", 2),
    block=True,
)


async def _fetch_team_result_for_scan(team_id: int) -> TeamResourceResult | None:
    try:
        return await asyncio.wait_for(
            _fetch_team_result(team_id, source="战队资源订阅"),
            timeout=get_team_resource_config().query_timeout_seconds,
        )
    except FinishedException:
        raise
    except (NotLoggedInError, DisconnectedError) as e:
        await mark_headless_unavailable(str(e), source="战队资源订阅")
        logger.warning(
            f"team resource scan unavailable, team id {team_id}: {e}"
        )
    except TimeoutError:
        logger.warning(f"team resource scan timeout, team id {team_id}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"team resource scan failed, team id {team_id}: {e}")
    return None


async def _scan_subscription(
    bot: Bot,
    group_id: int,
    subscription: TeamResourceSubscriptionConfig,
) -> None:
    for team_id in subscription.team_ids:
        result = await _fetch_team_result_for_scan(team_id)
        if result is None or result.resource >= subscription.threshold:
            continue

        await bot.send_group_msg(
            group_id=group_id,
            message=_format_resource_notice(result, subscription),
        )


async def scan_team_resource_subscriptions(bot: Bot) -> None:
    config = get_team_resource_config()
    if not config.enabled:
        return

    for subscription in config.subscriptions:
        group_id = resolve_group_id(subscription.group)
        if group_id is None:
            logger.warning(
                "team resource subscription skipped: "
                f"invalid group {subscription.group!r}"
            )
            continue
        if group_has_feature(group_id, TEAM_RESOURCE_FEATURE):
            await _scan_subscription(bot, group_id, subscription)


@team_resource_matcher.handle()
async def handle_team_resource(
    matcher: Matcher,
    event: GroupMessageEvent,
) -> None:
    team_ids = _team_ids_for_manual_query(subscriptions_for_group(event.group_id))
    replies: list[Message] = []
    for team_id in team_ids:
        result = await _fetch_team_result_for_manual(team_id)
        replies.append(
            Message(result.message)
            if isinstance(result, TeamResourceResult)
            else result
        )

    if replies:
        await finish_message_sequence(matcher, replies, event=event)


__all__ = [
    "scan_team_resource_subscriptions",
]
