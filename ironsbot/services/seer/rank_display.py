# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.config.models.seer import RankQueryConfig
    from ironsbot.core.platform import ActorRef, ConversationRef

_DISPLAY_LIMIT_RE = re.compile(
    r"^/\s*榜单(?:显示(?:条数|数量)?|默认(?:条数|数量)|条数)"
    r"\s*(\d+)(?:名|条)?\s*$",
    re.IGNORECASE,
)


class RankDisplayStore(Protocol):
    def get(self, conversation: ConversationRef) -> int | None: ...

    def set(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
        limit: int,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class RankDisplayService:
    config: RankQueryConfig
    configured_limits: Mapping[ConversationRef, int]
    store: RankDisplayStore

    def limit_for_conversation(
        self,
        conversation: ConversationRef | None,
    ) -> int:
        stored = self.store.get(conversation) if conversation is not None else None
        configured = (
            self.configured_limits.get(conversation)
            if conversation is not None
            else None
        )
        return self._clamp(
            stored
            or configured
            or self.config.display_limit
        )

    def set_conversation_limit(
        self,
        conversation: ConversationRef,
        actor: ActorRef,
        limit: int,
    ) -> None:
        self.store.set(conversation, actor, self._clamp(limit))

    def _clamp(self, value: int) -> int:
        return max(1, min(int(value), self.config.max_display_limit))


def parse_rank_display_limit_command(text: str) -> int | None:
    match = _DISPLAY_LIMIT_RE.fullmatch(text)
    return int(match.group(1)) if match is not None else None
