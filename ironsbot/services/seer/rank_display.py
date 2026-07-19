# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.config.models.seer import RankQueryConfig

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
    group_aliases: Mapping[str, int]
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
        direct = self.config.display_limits.get(str(group_id))
        if direct is not None:
            return direct
        return next(
            (
                self.config.display_limits[alias]
                for alias, alias_group_id in self.group_aliases.items()
                if alias_group_id == group_id
                and alias in self.config.display_limits
            ),
            None,
        )

    def _clamp(self, value: int) -> int:
        return max(1, min(int(value), self.config.max_display_limit))


def parse_rank_display_limit_command(text: str) -> int | None:
    match = _DISPLAY_LIMIT_RE.fullmatch(text)
    return int(match.group(1)) if match is not None else None
