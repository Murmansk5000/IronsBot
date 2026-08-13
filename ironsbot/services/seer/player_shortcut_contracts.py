# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral contracts for player detail shortcut commands."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ironsbot.core.semantic_requests import (
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
)
from ironsbot.services.operations.request_feedback import request_feedback_scope

if TYPE_CHECKING:
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.seer.local_rank import LocalRankService
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.player_service_models import PlayerBaseSnapshot
    from ironsbot.services.seer.query_result import QueryReply
    from ironsbot.services.seer.rank import RankService


PlayerShortcutKind = Literal["collection", "peak", "autocard"]
PlayerShortcutStatusSender = Callable[[str], Awaitable[None]]

_SHORTCUT_RE = re.compile(r"^(收集|巅峰|群星牌)(.*)$")
_KIND_BY_COMMAND: dict[str, PlayerShortcutKind] = {
    "收集": "collection",
    "巅峰": "peak",
    "群星牌": "autocard",
}
PLAYER_SHORTCUT_ACTIONS: dict[PlayerShortcutKind, ActionDefinition] = {
    "collection": ActionDefinition(
        "seer.player.collection",
        "收集与排行",
        cooldown_key="seer_player_collection",
    ),
    "peak": ActionDefinition(
        "seer.player.peak",
        "巅峰之战",
        cooldown_key="seer_player_peak",
    ),
    "autocard": ActionDefinition(
        "seer.player.autocard",
        "群星牌",
        cooldown_key="seer_player_autocard",
    ),
}


@dataclass(frozen=True, slots=True)
class PlayerShortcutCommand:
    """A resolved player detail shortcut ready for the player service."""

    kind: PlayerShortcutKind
    player_id: int
    base_snapshot: PlayerBaseSnapshot | None = None


@dataclass(frozen=True, slots=True)
class PlayerShortcutTargetCommand:
    """A parsed player detail shortcut before its player reference is resolved."""

    kind: PlayerShortcutKind
    player_reference: str | None


@dataclass(frozen=True, slots=True)
class PlayerShortcutDependencies:
    """Dependencies used to build a player detail shortcut reply."""

    rank: RankService
    local_rank: LocalRankService
    timeout_seconds: float = 30.0


def parse_player_shortcut_command(text: str) -> PlayerShortcutTargetCommand | None:
    """Parse a text shortcut without resolving its optional player target."""

    normalized = "".join(text.split())
    match = _SHORTCUT_RE.fullmatch(normalized)
    if match is None:
        return None
    command, player_reference = match.groups()
    player_reference = player_reference.strip()
    return PlayerShortcutTargetCommand(
        kind=_KIND_BY_COMMAND[command],
        player_reference=player_reference or None,
    )


def player_request_admission_message(label: str, *, queued: bool) -> str:
    if queued:
        return f"⏳ 已收到：{label}，已加入队列，完成后会直接发送结果。"
    return f"⏳ {label}正在查询，完成后会直接发送结果。"


async def execute_player_shortcut(
    service: PlayerService,
    command: PlayerShortcutCommand,
    actor: ActorRef,
    *,
    conversation: ConversationRef | None,
    send_status: PlayerShortcutStatusSender | None = None,
) -> QueryReply:
    """Run numeric-menu and text shortcuts through the same query path."""

    async def send_admission(label: str, *, queued: bool) -> None:
        if send_status is not None:
            await send_status(player_request_admission_message(label, queued=queued))

    with request_feedback_scope(
        PLAYER_SHORTCUT_ACTIONS[command.kind].label,
        send_admission if send_status is not None else None,
    ):
        return await service.shortcut(command, actor, conversation=conversation)


def player_shortcut_semantic_request(
    *,
    kind: PlayerShortcutKind,
    player_id: int,
    source: SemanticRequestSource,
) -> SemanticRequest:
    return SemanticRequest(
        action=PLAYER_SHORTCUT_ACTIONS[kind],
        target=SemanticTarget(key=str(player_id), display=f"米米号 {player_id}"),
        source=source,
    )
