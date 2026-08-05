# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple, Protocol

if TYPE_CHECKING:
    from ironsbot.config.models.seer import RankQueryConfig
    from ironsbot.core.onebot_references import OneBotReferenceResolver

_DISPLAY_LIMIT_RE = re.compile(
    r"^/\s*榜单(?:显示(?:条数|数量)?|默认(?:条数|数量)|条数)"
    r"\s*(\d+)(?:名|条)?\s*$",
    re.IGNORECASE,
)


class RankDisplayStore(Protocol):
    def get(self, group_id: int) -> int | None: ...

    def set(self, group_id: int, user_id: int, limit: int) -> None: ...


class RankDisplayService(NamedTuple):
    config: RankQueryConfig
    references: OneBotReferenceResolver
    store: RankDisplayStore

    def limit_for_group(self, group_id: int | None) -> int:
        stored = self.store.get(group_id) if group_id is not None else None
        return self._clamp(
            stored
            or self._configured_group_limit(group_id)
            or self.config.display_limit
        )

    def set_group_limit(self, group_id: int, user_id: int, limit: int) -> None:
        self.store.set(group_id, user_id, self._clamp(limit))

    def _configured_group_limit(self, group_id: int | None) -> int | None:
        if group_id is None:
            return None
        return next(
            (
                limit
                for reference, limit in self.config.display_limits.items()
                if self.references.resolve_group(
                    reference,
                    location=f"seer.rank.display_limits.{reference}",
                )
                == group_id
            ),
            None,
        )

    def _clamp(self, value: int) -> int:
        return max(1, min(int(value), self.config.max_display_limit))


def parse_rank_display_limit_command(text: str) -> int | None:
    match = _DISPLAY_LIMIT_RE.fullmatch(text)
    return int(match.group(1)) if match is not None else None
