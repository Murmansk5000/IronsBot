# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from nonebot.adapters import Event  # noqa: TC002
from nonebot.adapters.onebot.v11 import MessageEvent  # noqa: TC002
from nonebot.matcher import Matcher  # noqa: TC002
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002

from ironsbot.integrations.seer_data.sessions import SeerAPISession  # noqa: TC001
from ironsbot.runtime.matchers import CommandPolicy
from ironsbot.services.seer.countermark_stat_rank_messages import (
    build_countermark_stat_rank_message,
)
from ironsbot.services.seer.countermark_stat_rank_models import (  # noqa: TC001
    CountermarkStatRankCommand,
)
from ironsbot.services.seer.countermark_stat_rank_parsing import (
    parse_countermark_stat_rank_command,
)
from ironsbot.services.seer.countermark_stat_rank_ranking import (
    collect_countermark_rank_items,
)
from ironsbot.services.seer.countermark_stat_rank_repository import (
    MISSING_MINTMARK_QUALITY_MESSAGE,
    load_mintmark_quality_session,
    load_mintmarks,
)
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.utils.rule import no_reply

from ..group import SeerMatcherGroup, seer_feature_priority, seer_feature_rule

COUNTERMARK_STAT_RANK_KEY = "_countermark_stat_rank"


async def _is_countermark_stat_rank_command(event: Event, state: T_State) -> bool:
    command = parse_countermark_stat_rank_command(event.get_plaintext())
    if command is None:
        return False

    state[COUNTERMARK_STAT_RANK_KEY] = command
    return True


async def handle_countermark_stat_rank(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
    session: SeerAPISession,
) -> None:
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


def install(group: SeerMatcherGroup) -> None:
    matcher = group.on_message(
        policy=CommandPolicy.command("seer_countermark_stat_rank"),
        rule=seer_feature_rule("seer_mintmark")
        & Rule(_is_countermark_stat_rank_command)
        & no_reply(),
        priority=seer_feature_priority("seer_mintmark"),
    )
    matcher.append_handler(handle_countermark_stat_rank)


__all__ = ["install"]
