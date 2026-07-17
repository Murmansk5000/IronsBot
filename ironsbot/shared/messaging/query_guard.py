# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ironsbot.shared.features import is_superuser

from .rate_limits import peek_user_rate_limit, penalize_user_rate_limit

CooldownGetter = Callable[[], float]


@dataclass(slots=True)
class QueryGuard:
    namespace: str
    cooldown: CooldownGetter
    _in_progress: dict[int, int] = field(default_factory=dict)

    def in_progress_subject(self, user_id: int) -> int | None:
        if is_superuser(user_id):
            return None

        return self._in_progress.get(user_id)

    def set_in_progress(self, user_id: int, subject_id: int) -> None:
        if not is_superuser(user_id):
            self._in_progress[user_id] = subject_id

    def clear_in_progress(self, user_id: int) -> None:
        self._in_progress.pop(user_id, None)

    def remaining_seconds(self, user_id: int) -> int:
        return peek_user_rate_limit(
            self.namespace,
            user_id,
            self.cooldown(),
            exempt=is_superuser(user_id),
        )

    def finish(self, user_id: int) -> None:
        self.clear_in_progress(user_id)
        penalize_user_rate_limit(
            self.namespace,
            user_id,
            self.cooldown(),
            exempt=is_superuser(user_id),
        )
