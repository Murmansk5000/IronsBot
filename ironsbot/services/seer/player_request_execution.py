# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from ironsbot.core.request_coordination import send_request_response

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.semantic_requests import SemanticRequest
    from ironsbot.services.operations.headless_pool import HeadlessRequestPriority
    from ironsbot.services.seer.player_request_protection import (
        PlayerRequestProtectionService,
    )

T = TypeVar("T")


async def run_player_live_request(  # noqa: PLR0913
    requests: PlayerRequestProtectionService | None,
    operation: Callable[[], Awaitable[T]],
    *,
    user_id: int,
    label: str,
    semantic_request: SemanticRequest | None = None,
    priority: HeadlessRequestPriority | None = None,
) -> T:
    """Dispatch a previously admitted foreground request to the worker pool."""

    if requests is None:
        await send_request_response(queued=False)
        return await operation()
    return await requests.run(
        operation,
        user_id=user_id,
        label=label,
        semantic_request=semantic_request,
        priority=priority,
    )
