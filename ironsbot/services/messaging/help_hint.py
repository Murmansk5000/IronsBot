# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from random import choice
from typing import TYPE_CHECKING, Protocol

from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter

if TYPE_CHECKING:
    from ironsbot.core.features import HelpConfig
    from ironsbot.core.onebot_references import OneBotReferenceResolver


class CommandHintCandidate(Protocol):
    def poke_text(self) -> str: ...


CommandHintCandidates = Callable[
    [int | None, int, str | None, tuple[str, ...]],
    Sequence[CommandHintCandidate],
]


class PokeLikeEvent(Protocol):
    self_id: int
    target_id: int


POKE_HINT_HELP_SUFFIX = "发送“帮助”可查看全部指令。"


def is_poke_at_bot(event: PokeLikeEvent) -> bool:
    return event.target_id == event.self_id


def _get_poke_reply(
    target_id: int | None,
    *,
    resolve: Callable[..., int],
    replies: Mapping[str, str],
    location: str,
) -> str | None:
    if target_id is None:
        return None

    for raw_target, message in replies.items():
        if resolve(raw_target, location=f"{location}.{raw_target}") == target_id:
            return message
    return None


@dataclass(slots=True)
class HelpHintService:
    config: HelpConfig
    references: OneBotReferenceResolver
    poke_hint_candidates: CommandHintCandidates | None = None
    chooser: Callable[
        [Sequence[CommandHintCandidate]], CommandHintCandidate
    ] = choice
    limiter: SlidingWindowRateLimiter = field(
        default_factory=SlidingWindowRateLimiter
    )

    def get_poke_reply(self, *, group_id: int | None, user_id: int) -> str | None:
        return _get_poke_reply(
            user_id,
            resolve=self.references.resolve_user,
            replies=self.config.poke_user_replies,
            location="features.help.poke_user_replies",
        ) or _get_poke_reply(
            group_id,
            resolve=self.references.resolve_group,
            replies=self.config.poke_replies,
            location="features.help.poke_replies",
        )

    def get_default_poke_hint(
        self,
        *,
        group_id: int | None,
        user_id: int,
        group_role: str | None = None,
    ) -> str | None:
        if self.poke_hint_candidates is None:
            return None
        candidates = self.poke_hint_candidates(
            group_id,
            user_id,
            group_role,
            tuple(self.config.ignored_plugins),
        )
        if not candidates:
            return None
        selected = self.chooser(candidates)
        return f"{selected.poke_text()}\n{POKE_HINT_HELP_SUFFIX}"

    def can_send(self, group_id: int | None, *, now: float | None = None) -> bool:
        if group_id is None:
            return True
        return (
            self.limiter.hit(
                "help_hint",
                group_id,
                window_seconds=self.config.hint_window_seconds,
                max_events=self.config.hint_max_per_window,
                now=now,
            )
            >= 0
        )
