# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.rule import Rule

from ironsbot.core.commands import command_text_matches
from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
)
from ironsbot.runtime.matchers import CommandPolicy, MatcherRegistry
from ironsbot.services.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.services.team_resource_adapter import (
    TeamResourceResult,
    fetch_team_resource_result,
)
from ironsbot.services.team_resource_subscriptions import TeamResourceSubscriptionUpdate
from ironsbot.shared.features import group_has_feature, is_group_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    MessageTarget,
    finish_event_reply,
    finish_message_sequence,
    send_target_messages,
)
from ironsbot.shared.messaging.text import build_message
from ironsbot.shared.permissions import can_manage_group_event
from ironsbot.utils.rule import no_reply

from .config import (
    at_users_for_subscription,
    default_at_user_ids,
    get_team_resource_config,
    get_team_resource_store,
    get_team_resource_subscriptions,
    subscriptions_for_group,
)

if TYPE_CHECKING:
    from nonebot.matcher import Matcher

    from ironsbot.services.team_resource_subscriptions import (
        TeamResourceSubscription,
    )

TEAM_RESOURCE_FEATURE = "team_resource_subscription"
TEAM_ID_MIN = 100_000
TEAM_ID_MAX = 2_000_000_000

_ADD_PREFIXES = ("订阅战队", "添加战队", "战队订阅")
_REMOVE_PREFIXES = ("取消订阅战队", "删除订阅战队", "战队取消订阅")
_LIST_COMMANDS = ("战队订阅", "订阅战队", "本群战队")

_ADD_ACTION = "add"
_REMOVE_ACTION = "remove"
_LIST_ACTION = "list"
TEAM_RESOURCE_MANAGE_ACTION_KEY = "_team_resource_manage_action"
TEAM_RESOURCE_MANAGE_TEAM_ID_KEY = "_team_resource_manage_team_id"
TEAM_RESOURCE_MANAGE_THRESHOLD_KEY = "_team_resource_manage_threshold"
_YES_REPLIES = frozenset(("是", "yes", "y", "确认", "确定"))
_NO_REPLIES = frozenset(("否", "no", "n", "取消"))

@dataclass(frozen=True, slots=True)
class TeamResourceManageCommand:
    action: str
    team_id: int | None = None
    threshold: int | None = None


def _format_resource_notice(
    result: TeamResourceResult,
    subscription: TeamResourceSubscription,
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


async def _is_team_resource_query(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False

    config = get_team_resource_config()
    if not config.enabled:
        return False

    if not is_group_feature_allowed(
        event.user_id,
        event.group_id,
        TEAM_RESOURCE_FEATURE,
    ):
        return False

    return command_text_matches(event.get_plaintext(), config.commands)


def _parse_team_resource_manage_command(text: str) -> TeamResourceManageCommand | None:
    stripped = re.sub(r"\s+", " ", text.strip())
    if stripped in _LIST_COMMANDS:
        return TeamResourceManageCommand(_LIST_ACTION)

    for prefix in _REMOVE_PREFIXES:
        command = _parse_prefixed_team_command(stripped, prefix)
        if command is not None and command.team_id is not None:
            return TeamResourceManageCommand(_REMOVE_ACTION, command.team_id)

    for prefix in _ADD_PREFIXES:
        command = _parse_prefixed_team_command(stripped, prefix)
        if command is not None:
            if command.team_id is None:
                return TeamResourceManageCommand(_LIST_ACTION)
            return TeamResourceManageCommand(
                _ADD_ACTION,
                command.team_id,
                command.threshold,
            )

    return None


def _parse_prefixed_team_command(
    text: str,
    prefix: str,
) -> TeamResourceManageCommand | None:
    if not text.startswith(prefix):
        return None
    rest = text[len(prefix) :].strip()
    if not rest:
        return TeamResourceManageCommand(_LIST_ACTION)

    team_id_match = re.match(r"\d+", rest)
    if team_id_match is None:
        return TeamResourceManageCommand(_LIST_ACTION)

    team_id = int(team_id_match.group())
    if not _is_valid_team_id(team_id):
        return TeamResourceManageCommand(_LIST_ACTION)

    threshold = _parse_subscription_threshold(rest[team_id_match.end() :])
    return TeamResourceManageCommand(_ADD_ACTION, team_id, threshold)


def _parse_subscription_threshold(text: str) -> int | None:
    """Read only a standalone numeric argument after the team ID.

    QQ mentions may appear as text such as ``@123456`` in malformed/manual
    input. They must never be mistaken for the resource threshold.
    """

    match = re.search(r"(?<!\S)(\d+)(?!\S)", text)
    return int(match.group(1)) if match is not None else None


def _has_manual_qq_mention(text: str) -> bool:
    return re.search(r"@\d{5,}", text) is not None


def _is_valid_team_id(team_id: int) -> bool:
    return TEAM_ID_MIN <= team_id <= TEAM_ID_MAX


async def _is_team_resource_manage(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    if not get_team_resource_config().enabled:
        return False
    if not is_group_feature_allowed(
        event.user_id,
        event.group_id,
        TEAM_RESOURCE_FEATURE,
    ):
        return False
    return _parse_team_resource_manage_command(event.get_plaintext()) is not None


def parse_team_resource_prompt_choice(text: str) -> bool | None:
    normalized = text.strip().casefold()
    if normalized in _YES_REPLIES:
        return True
    if normalized in _NO_REPLIES:
        return False
    return None


async def _is_team_resource_prompt_choice(event: MessageEvent) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    if not get_team_resource_config().enabled:
        return False
    if parse_team_resource_prompt_choice(event.get_plaintext()) is None:
        return False
    if not can_manage_group_event(event):
        return False
    if not is_group_feature_allowed(
        event.user_id,
        event.group_id,
        TEAM_RESOURCE_FEATURE,
    ):
        return False
    return get_team_resource_store().get_pending_prompt(event.group_id) is not None


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
        logger.warning(f"team resource scan unavailable, team id {team_id}: {e}")
    except TimeoutError:
        logger.warning(f"team resource scan timeout, team id {team_id}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"team resource scan failed, team id {team_id}: {e}")
    return None


async def _scan_subscription(subscription: TeamResourceSubscription) -> None:
    result = await _fetch_team_result_for_scan(subscription.team_id)
    if result is None:
        return

    get_team_resource_store().update_team_name(
        group_id=subscription.group_id,
        team_id=subscription.team_id,
        team_name=result.team_name,
    )
    if result.resource >= subscription.threshold:
        return

    await send_target_messages(
        [MessageTarget("group", subscription.group_id)],
        _format_resource_notice(result, subscription),
        action_name="team resource subscription notice",
        interval_seconds=0,
    )


async def scan_team_resource_subscriptions() -> None:
    config = get_team_resource_config()
    if not config.enabled:
        return

    for subscription in get_team_resource_subscriptions():
        if group_has_feature(subscription.group_id, TEAM_RESOURCE_FEATURE):
            await _scan_subscription(subscription)


async def parse_team_resource_manage(
    matcher: Matcher,
    event: GroupMessageEvent,
) -> None:
    command = _parse_team_resource_manage_command(event.get_plaintext())
    if command is None:
        await matcher.finish()

    if command.action == _LIST_ACTION:
        await finish_event_reply(
            matcher,
            event,
            _format_group_subscriptions(event.group_id),
        )
        return

    if not can_manage_group_event(event):
        await finish_event_reply(
            matcher,
            event,
            "只有群主、管理员或超级管理员可以修改本群战队订阅。",
        )
        return

    if command.team_id is None or not _is_valid_team_id(command.team_id):
        await finish_event_reply(
            matcher,
            event,
            "战队ID范围必须在 100000~2000000000 之间。",
        )
        return

    if command.action == _REMOVE_ACTION:
        deleted = get_team_resource_store().delete(
            group_id=event.group_id,
            team_id=command.team_id,
        )
        message = (
            f"已取消本群战队订阅：{command.team_id}。"
            if deleted
            else f"本群没有订阅战队：{command.team_id}。"
        )
        await finish_event_reply(matcher, event, message)
        return

    if (
        _has_manual_qq_mention(event.get_plaintext())
        and not _at_user_ids_from_event(event)
    ):
        await finish_event_reply(
            matcher,
            event,
            "提醒对象请用 QQ 的 @ 选人功能添加；手动输入 @QQ号 不会保存为提醒对象。",
        )
        return

    result = await _fetch_team_result_for_manual(command.team_id)
    if not isinstance(result, TeamResourceResult):
        await finish_event_reply(matcher, event, result)
        return

    threshold = command.threshold or get_team_resource_config().default_threshold
    at_user_ids = _at_user_ids_from_event(event) or default_at_user_ids()
    get_team_resource_store().upsert(
        TeamResourceSubscriptionUpdate(
            group_id=event.group_id,
            team_id=result.team_id,
            team_name=result.team_name,
            threshold=threshold,
            at_user_ids=tuple(at_user_ids),
            operator_id=event.user_id,
        )
    )
    at_text = _format_at_users(at_user_ids)
    await finish_event_reply(
        matcher,
        event,
        (
            f"已订阅本群战队：{result.team_name}（{result.team_id}）。\n"
            f"资源阈值：{threshold}\n"
            f"提醒对象：{at_text}"
        ),
    )


async def handle_team_resource_prompt_choice(
    matcher: Matcher,
    event: GroupMessageEvent,
) -> None:
    choice = parse_team_resource_prompt_choice(event.get_plaintext())
    prompt = get_team_resource_store().get_pending_prompt(event.group_id)
    if choice is None or prompt is None:
        await matcher.finish()

    get_team_resource_store().mark_prompt_handled(
        group_id=event.group_id,
        handled_by=event.user_id,
        accepted=choice,
    )
    if not choice:
        await finish_event_reply(
            matcher,
            event,
            "已跳过本群战队订阅提示。以后需要时，群主/管理员仍可发送“订阅战队123456”添加。",
        )
        return

    threshold = get_team_resource_config().default_threshold
    at_user_ids = default_at_user_ids()
    get_team_resource_store().upsert(
        TeamResourceSubscriptionUpdate(
            group_id=event.group_id,
            team_id=prompt.team_id,
            team_name=prompt.team_name,
            threshold=threshold,
            at_user_ids=tuple(at_user_ids),
            operator_id=event.user_id,
        )
    )
    await finish_event_reply(
        matcher,
        event,
        (
            "已订阅本群战队："
            f"{prompt.team_name or prompt.team_id}（{prompt.team_id}）。\n"
            f"资源阈值：{threshold}\n"
            f"提醒对象：{_format_at_users(at_user_ids)}\n"
            "还可以继续发送“订阅战队123456”添加更多战队。"
        ),
    )


async def handle_team_resource(
    matcher: Matcher,
    event: GroupMessageEvent,
) -> None:
    subscriptions = subscriptions_for_group(event.group_id)
    if not subscriptions:
        await finish_event_reply(
            matcher,
            event,
            "本群还没有订阅战队。群主/管理员可发送“订阅战队123456”添加。",
        )
        return

    replies: list[Message] = []
    for subscription in subscriptions:
        result = await _fetch_team_result_for_manual(subscription.team_id)
        replies.append(
            Message(result.message)
            if isinstance(result, TeamResourceResult)
            else result
        )

    if replies:
        await finish_message_sequence(matcher, replies, event=event)


def install(registry: MatcherRegistry) -> None:
    manage_matcher = registry.on_message(
        policy=CommandPolicy.command("team_resource_manage"),
        rule=Rule(_is_team_resource_manage) & no_reply(allow_at=True),
        priority=get_matcher_priority("team_resource_subscription", 1),
        block=True,
    )
    manage_matcher.append_handler(parse_team_resource_manage)

    prompt_matcher = registry.on_message(
        policy=CommandPolicy.exempt(
            "second-level team subscription confirmation"
        ),
        rule=Rule(_is_team_resource_prompt_choice) & no_reply(),
        priority=get_matcher_priority("team_resource_subscription", 0),
        block=True,
    )
    prompt_matcher.append_handler(handle_team_resource_prompt_choice)

    query_matcher = registry.on_message(
        policy=CommandPolicy.command("team_resource_query"),
        rule=Rule(_is_team_resource_query) & no_reply(),
        priority=get_matcher_priority("team_resource_subscription", 2),
        block=True,
    )
    query_matcher.append_handler(handle_team_resource)


def _format_group_subscriptions(group_id: int) -> str:
    subscriptions = subscriptions_for_group(group_id)
    if not subscriptions:
        return (
            "本群还没有订阅战队。\n"
            "群主/管理员可发送：订阅战队123456\n"
            "也可发送：订阅战队123456 1000 @提醒人"
        )

    lines = ["本群战队订阅："]
    for index, subscription in enumerate(subscriptions, start=1):
        name = (
            f"{subscription.team_name}（{subscription.team_id}）"
            if subscription.team_name
            else str(subscription.team_id)
        )
        lines.append(
            f"{index}. {name}｜阈值 {subscription.threshold}"
            f"｜提醒 {_format_at_users(subscription.at_user_ids)}"
        )
    lines.append("")
    lines.append("群主/管理员可发送：订阅战队123456 1000 @提醒人")
    lines.append("取消订阅：取消订阅战队123456")
    return "\n".join(lines)


def _at_user_ids_from_event(event: GroupMessageEvent) -> tuple[int, ...]:
    user_ids: list[int] = []
    for segment in event.message:
        if segment.type != "at":
            continue
        qq = str(segment.data.get("qq", ""))
        if qq.isdigit():
            user_ids.append(int(qq))
    return tuple(dict.fromkeys(user_ids))


def _format_at_users(user_ids: tuple[int, ...]) -> str:
    if not user_ids:
        return "无"
    return "、".join(str(user_id) for user_id in user_ids)


__all__ = [
    "parse_team_resource_prompt_choice",
    "scan_team_resource_subscriptions",
]
