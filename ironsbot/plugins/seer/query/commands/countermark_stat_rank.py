# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.adapters.onebot.v11 import (  # noqa: TC002 - NoneBot resolves it at runtime
    MessageEvent,
)
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves it at runtime
from nonebot.rule import Rule
from nonebot.typing import T_State  # noqa: TC002 - NoneBot resolves it at runtime

from ironsbot.runtime.matchers import CommandPolicy, bind, bind_async
from ironsbot.runtime.replies import finish_event_reply
from ironsbot.runtime.rules import explicit_command
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from ironsbot.services.seer.countermark_stat_rank import (
        CountermarkStatRankService,
    )
    from ironsbot.services.seer.countermark_stat_rank_models import (
        CountermarkStatRankCommand,
    )

COUNTERMARK_STAT_RANK_KEY = "_countermark_stat_rank"


def _match_command(
    service: CountermarkStatRankService,
    event: Event,
    state: T_State,
) -> bool:
    command = service.parse_command(event.get_plaintext())
    if command is None:
        return False
    state[COUNTERMARK_STAT_RANK_KEY] = command
    return True


async def _handle_command(
    service: CountermarkStatRankService,
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    command: CountermarkStatRankCommand = state[COUNTERMARK_STAT_RANK_KEY]
    try:
        reply = service.query(command)
    except DataUnavailableError:
        reply = DATABASE_UNAVAILABLE_MESSAGE
    await finish_event_reply(matcher, event, reply)


def install(group: SeerMatcherGroup) -> None:
    service = group.resources.countermark_rank
    matcher = group.on_message(
        policy=CommandPolicy.command(
            "seer_countermark_stat_rank",
            help_ids=("seer.mintmark.rank",),
        ),
        rule=seer_feature_rule(group.features, "seer_mintmark")
        & Rule(bind(_match_command, service))
        & explicit_command(),
        priority=group.matcher_priority("seer_mintmark"),
    )
    matcher.append_handler(bind_async(_handle_command, service))
