# SPDX-License-Identifier: GPL-3.0-or-later

import asyncio
import re
from functools import partial
from typing import Any, cast

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.config.models.seer import TeamQueryConfig
from ironsbot.integrations.headless_seer.activity import headless_operation
from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.services.operations.headless import HeadlessService
from ironsbot.services.seer.errors import format_socket_recv_error
from ironsbot.services.seer.resources import SeerQueryResources
from ironsbot.services.seer.team import (
    format_team_generic_error_message,
    format_team_info,
    format_team_socket_error_message,
    format_team_timeout_message,
    format_team_unavailable_message,
)
from ironsbot.services.team_resource_subscriptions import TeamResourceService
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.shared.permissions import can_manage_group_event
from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import SeerMatcherGroup, seer_feature_rule

TEAM_IDS_KEY = "team_ids"
TEAM_ID_MIN = 100_000
TEAM_ID_MAX = 2_000_000_000
TEAM_RESOURCE_FEATURE = "team_resource_subscription"

def _parse_team_ids(text: str) -> list[int]:
    team_ids: list[int] = []
    for item in re.findall(r"\d+", text):
        team_id = int(item)
        if TEAM_ID_MIN <= team_id <= TEAM_ID_MAX:
            team_ids.append(team_id)
    return list(dict.fromkeys(team_ids))


async def _has_team_id_args(state: T_State) -> bool:
    return bool(_parse_team_ids(parse_string_arg(state)))


async def _finish_team_query_failure(
    matcher: Matcher,
    event: MessageEvent,
    message: str,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        message,
        mention_sender=True,
    )


async def validate_team_id(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    team_ids = _parse_team_ids(parse_string_arg(state))
    if not team_ids:
        await finish_event_reply(
            matcher,
            event,
            "❌ 战队ID范围必须在 100000~2000000000 之间！",
            mention_sender=True,
        )
        return
    state[TEAM_IDS_KEY] = team_ids


def _team_subscription_prompt(
    service: TeamResourceService,
    event: MessageEvent,
    team_info: object,
) -> str | None:
    if not isinstance(event, GroupMessageEvent):
        return None
    if not can_manage_group_event(service.features, event):
        return None

    if not service.config.enabled:
        return None
    if not service.features.is_group_feature_allowed(
        event.user_id,
        event.group_id,
        TEAM_RESOURCE_FEATURE,
    ):
        return None

    if service.store.has_prompted_group(event.group_id):
        return None

    typed_team_info = cast("Any", team_info)
    team_id = int(typed_team_info.team_id)
    team_name = str(typed_team_info.name or "")
    service.store.mark_group_prompted(
        group_id=event.group_id,
        team_id=team_id,
        team_name=team_name,
        prompted_by=event.user_id,
    )
    label = f"{team_name}（{team_id}）" if team_name else str(team_id)
    return (
        f"本群可以订阅战队 {label} 的资源提醒。\n"
        "是否订阅这个战队？回复“是”或“y”订阅，回复“否”或“n”跳过。\n"
        "本群只提示一次；之后群主/管理员仍可发送“订阅战队123456”添加更多战队。"
    )


async def _query_team_info(
    team_id: int,
    headless: HeadlessService,
    config: TeamQueryConfig,
) -> tuple[str, object]:
    game = headless.get_game()
    with headless_operation(
        "战队查询",
        f"战队 {team_id}",
        source="战队查询",
    ):
        team_info = await asyncio.wait_for(
            game.get_team_info(team_id),
            timeout=config.timeout_seconds,
        )
    await headless.mark_available(source="战队查询", user_id=int(game.user_id))
    return (
        format_team_info(
            team_info,
            set(config.sections),
        ),
        team_info,
    )


async def _collect_team_query_messages(
    service: TeamResourceService,
    team_ids: list[int],
    event: MessageEvent,
    headless: HeadlessService,
    query_config: TeamQueryConfig,
) -> tuple[list[str], str | None]:
    messages: list[str] = []
    prompt: str | None = None

    for team_id in team_ids:
        try:
            team_message, team_info = await _query_team_info(
                team_id,
                headless,
                query_config,
            )
        except (NotLoggedInError, DisconnectedError):
            raise
        except TimeoutError:
            messages.append(format_team_timeout_message(team_id))
            continue
        except SocketRecvError as e:
            messages.append(
                format_team_socket_error_message(
                    team_id,
                    format_socket_recv_error(e),
                )
            )
            continue
        except Exception as e:  # noqa: BLE001
            messages.append(format_team_generic_error_message(team_id, e))
            continue

        messages.append(team_message)
        if prompt is None:
            prompt = _team_subscription_prompt(service, event, team_info)

    return messages, prompt


async def handle_team(
    resources: SeerQueryResources,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    team_ids: list[int] = state[TEAM_IDS_KEY]

    try:
        messages, prompt = await _collect_team_query_messages(
            resources.team_resource,
            team_ids,
            event,
            resources.headless,
            resources.config.team,
        )
    except FinishedException:
        raise
    except (NotLoggedInError, DisconnectedError) as e:
        await resources.headless.mark_unavailable(str(e), source="战队查询")
        await _finish_team_query_failure(
            matcher,
            event,
            format_team_unavailable_message(team_ids[0]),
        )
        return

    if prompt is not None:
        messages.append(prompt)

    await finish_event_reply(
        matcher,
        event,
        "\n\n".join(messages),
        mention_sender=True,
    )


def install(group: SeerMatcherGroup) -> None:
    matcher = group.on_message(
        policy=CommandPolicy.command("seer_team"),
        rule=seer_feature_rule(group.resources.features, "seer_team")
        & (
            startswith_or_endswith(
                prefixes=("战队", "查询战队信息"),
                suffixes=(),
            )
            & Rule(_has_team_id_args)
            & no_reply()
        ),
        priority=group.matcher_priority("seer_team"),
    )
    matcher.append_handler(validate_team_id)
    matcher.append_handler(partial(handle_team, group.resources))
