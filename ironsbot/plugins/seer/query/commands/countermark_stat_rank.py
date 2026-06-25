# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageEvent
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.plugins.seer_data.db import SeerAPISession
from ironsbot.services.seer.countermark_stat_rank import (
    MISSING_MINTMARK_QUALITY_MESSAGE,
    CountermarkStatRankCommand,
    build_countermark_stat_rank_message,
    collect_countermark_rank_items,
    load_mintmark_quality_session,
    load_mintmarks,
    parse_countermark_stat_rank_command,
)
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from ..group import matcher_group, seer_feature_rule

COUNTERMARK_STAT_RANK_KEY = "_countermark_stat_rank"
COUNTERMARK_STAT_RANK_PLUGIN_NAME = "seer_countermark_stat_rank"


async def _is_countermark_stat_rank_command(event: Event, state: T_State) -> bool:
    command = parse_countermark_stat_rank_command(event.get_plaintext())
    if command is None:
        return False

    state[COUNTERMARK_STAT_RANK_KEY] = command
    return True


countermark_stat_rank_matcher = matcher_group.on_message(
    rule=seer_feature_rule("seer_mintmark")
    & Rule(_is_countermark_stat_rank_command)
    & no_reply(),
)


class CountermarkStatRankPlugin:
    name = COUNTERMARK_STAT_RANK_PLUGIN_NAME
    feature = "seer_mintmark"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        matcher = context.matcher
        if matcher is None:
            return

        state = context.state if context.state is not None else {}
        session: SeerAPISession = context.data["session"]
        command: CountermarkStatRankCommand = state[COUNTERMARK_STAT_RANK_KEY]
        quality_map = load_mintmark_quality_session(session)
        if command.angle_count is not None and not quality_map:
            await finish_event_reply(
                matcher,
                event,
                MISSING_MINTMARK_QUALITY_MESSAGE,
            )
            return

        mintmarks = load_mintmarks(session)
        items = collect_countermark_rank_items(mintmarks, command, quality_map)
        await finish_event_reply(
            matcher,
            event,
            build_countermark_stat_rank_message(command, items),
        )


register_plugin(CountermarkStatRankPlugin())


@countermark_stat_rank_matcher.handle()
async def handle_countermark_stat_rank(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    session: SeerAPISession,
) -> None:
    await dispatch_plugin(
        plugin_name=COUNTERMARK_STAT_RANK_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        session=session,
    )
