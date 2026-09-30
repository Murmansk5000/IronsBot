# SPDX-License-Identifier: GPL-3.0-or-later
"""Platform-neutral contracts for player detail shortcut commands."""

from __future__ import annotations

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


PlayerShortcutKind = Literal["collection", "peak", "autocard", "beast_rank"]
PlayerShortcutStatusSender = Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PlayerShortcutSpec:
    kind: PlayerShortcutKind
    name: str
    label: str
    cache_key: str = ""


PLAYER_SHORTCUT_SPECS = (
    PlayerShortcutSpec(
        "collection", "收集", "收集与排行", "_player_collection_message"
    ),
    PlayerShortcutSpec("peak", "巅峰", "巅峰之战", "_player_peak_message"),
    PlayerShortcutSpec("autocard", "群星牌", "群星牌排名", "_player_autocard_message"),
    PlayerShortcutSpec("beast_rank", "神兽榜", "神兽榜"),
)
_KIND_BY_COMMAND: dict[str, PlayerShortcutKind] = {
    spec.name: spec.kind for spec in PLAYER_SHORTCUT_SPECS
}
PLAYER_SHORTCUT_NAMES = tuple(_KIND_BY_COMMAND)
PLAYER_SHORTCUT_ACTIONS = {
    spec.kind: ActionDefinition(
        f"seer.player.{spec.kind}",
        spec.label,
        cooldown_key=f"seer_player_{spec.kind}",
    )
    for spec in PLAYER_SHORTCUT_SPECS
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
    timeout_seconds: float
    detail_timeout_seconds: float
    rank_timeout_seconds: float


def parse_player_shortcut_command(text: str) -> PlayerShortcutTargetCommand | None:
    """Parse a text shortcut without resolving its optional player target."""

    normalized = "".join(text.split())
    for command, kind in _KIND_BY_COMMAND.items():
        if normalized.startswith(command):
            return PlayerShortcutTargetCommand(
                kind=kind, player_reference=normalized[len(command) :] or None
            )
    return None


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
