# SPDX-License-Identifier: MIT
"""Best-effort display identity; never infer a task bot from notice routing."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

from nonebot import get_bot

from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.platform import Platform

_NAMES: dict[str, tuple[float, str]] = {}
_TTL = 600


async def resolve_execution_identity(
    identity: ExecutionIdentity,
    *,
    aliases: Mapping[str, int],
) -> ExecutionIdentity:
    if identity.platform is not Platform.ONEBOT:
        return identity
    cached_at, nickname = _NAMES.get(identity.account_id, (0.0, ""))
    if monotonic() - cached_at >= _TTL or not nickname:
        try:
            bot = get_bot(identity.account_id)
            response = await asyncio.wait_for(bot.call_api("get_login_info"), timeout=2)
            nickname = str(response.get("nickname") or "").strip()
            if nickname:
                _NAMES[identity.account_id] = (monotonic(), nickname)
        except Exception:  # noqa: BLE001 - task delivery is independent of nickname API
            nickname = ""
    name = nickname or next(
        (key for key, value in aliases.items() if str(value) == identity.account_id),
        identity.display_name or identity.account_id,
    )
    return ExecutionIdentity(identity.platform, identity.account_id, name)
