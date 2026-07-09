# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio

from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.exception import FinishedException
from nonebot.matcher import Matcher
from nonebot.typing import T_State

from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.headless_seer_notice.state import (
    mark_headless_available,
    mark_headless_unavailable,
)
from ironsbot.services.seer.client import get_game_client
from ironsbot.services.seer.errors import format_socket_recv_error
from ironsbot.services.seer.team import (
    format_team_generic_error_message,
    format_team_info,
    format_team_socket_error_message,
    format_team_timeout_message,
    format_team_unavailable_message,
    team_query_in_progress_message,
    team_query_wait_message,
)
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.shared.messaging.query_guard import QueryGuard
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..config import get_team_query_config
from ..group import matcher_group, seer_feature_priority, seer_feature_rule
from ._args import has_numeric_arg, parse_numeric_id

TEAM_ID_KEY = "team_id"
TEAM_PLUGIN_NAME = "seer_team"
TEAM_QUERY_GUARD = QueryGuard(
    success_namespace="seer.team_query.success",
    failure_namespace="seer.team_query.failure",
    success_cooldown=lambda: get_team_query_config().rate_limit_seconds,
    failure_cooldown=lambda: get_team_query_config().failure_rate_limit_seconds,
)

team_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_team")
    & (
        startswith_or_endswith(prefixes=("战队", "查询战队信息"), suffixes=())
        & has_numeric_arg
        & no_reply()
    ),
    priority=seer_feature_priority("seer_team"),
)


async def _finish_team_query_failure(
    matcher: Matcher,
    event: MessageEvent,
    message: str,
) -> None:
    TEAM_QUERY_GUARD.clear_in_progress(event.user_id)
    TEAM_QUERY_GUARD.penalize_failure(event.user_id)
    await finish_event_reply(
        matcher,
        event,
        message,
        mention_sender=True,
    )


class CustomTeamPlugin:
    name = TEAM_PLUGIN_NAME
    feature = "seer_team"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        matcher = context.matcher
        if matcher is None:
            return

        state = context.state if context.state is not None else {}
        if context.action == "validate":
            await self._validate_team_id(matcher, event, state)
            return
        if context.action == "query":
            await self._handle_team(matcher, event, state)

    async def _validate_team_id(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        state[TEAM_ID_KEY] = await parse_numeric_id(
            matcher,
            state,
            min_value=100000,
            max_value=2_000_000_000,
            error_message="❌ 战队ID范围必须在 100000~2000000000 之间！",
        )
        team_id: int = state[TEAM_ID_KEY]

        in_progress_team_id = TEAM_QUERY_GUARD.in_progress_subject(event.user_id)
        if in_progress_team_id is not None:
            await finish_event_reply(
                matcher,
                event,
                team_query_in_progress_message(in_progress_team_id),
                mention_sender=True,
            )

        remaining = TEAM_QUERY_GUARD.remaining_seconds(event.user_id)
        if remaining > 0:
            await finish_event_reply(
                matcher,
                event,
                team_query_wait_message(remaining),
                mention_sender=True,
            )

        TEAM_QUERY_GUARD.set_in_progress(event.user_id, team_id)

    async def _handle_team(
        self,
        matcher: Matcher,
        event: MessageEvent,
        state: T_State,
    ) -> None:
        team_id: int = state[TEAM_ID_KEY]

        try:
            game = get_game_client()
            team_config = get_team_query_config()
            team_info = await asyncio.wait_for(
                game.get_team_info(team_id),
                timeout=team_config.timeout_seconds,
            )
            await mark_headless_available(source="战队查询", user_id=int(game.user_id))
            team_message = format_team_info(
                team_info,
                set(team_config.sections),
            )
        except FinishedException:
            raise
        except (NotLoggedInError, DisconnectedError) as e:
            await mark_headless_unavailable(str(e), source="战队查询")
            await _finish_team_query_failure(
                matcher,
                event,
                format_team_unavailable_message(team_id),
            )
            return
        except TimeoutError:
            await _finish_team_query_failure(
                matcher,
                event,
                format_team_timeout_message(team_id),
            )
            return
        except SocketRecvError as e:
            await _finish_team_query_failure(
                matcher,
                event,
                format_team_socket_error_message(team_id, format_socket_recv_error(e)),
            )
            return
        except Exception as e:  # noqa: BLE001
            await _finish_team_query_failure(
                matcher,
                event,
                format_team_generic_error_message(team_id, e),
            )
            return

        TEAM_QUERY_GUARD.clear_in_progress(event.user_id)
        TEAM_QUERY_GUARD.penalize_success(event.user_id)
        await finish_event_reply(
            matcher,
            event,
            team_message,
            mention_sender=True,
        )


register_plugin(CustomTeamPlugin())


@team_matcher.handle()
async def validate_team_id(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=TEAM_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="validate",
    )


@team_matcher.handle()
async def handle_team(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=TEAM_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="query",
    )
