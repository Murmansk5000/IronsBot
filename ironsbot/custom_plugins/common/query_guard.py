# SPDX-License-Identifier: MIT
from collections.abc import Callable
from dataclasses import dataclass, field

from ironsbot.custom_plugins.feature_policy import is_superuser
from ironsbot.custom_plugins.message_actions import (
    peek_user_rate_limit,
    penalize_user_rate_limit,
)

CooldownGetter = Callable[[], float]


@dataclass(slots=True)
class QueryGuard:
    success_namespace: str
    failure_namespace: str
    success_cooldown: CooldownGetter
    failure_cooldown: CooldownGetter
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
        exempt = is_superuser(user_id)
        success_remaining = peek_user_rate_limit(
            self.success_namespace,
            user_id,
            self.success_cooldown(),
            exempt=exempt,
        )
        failure_remaining = peek_user_rate_limit(
            self.failure_namespace,
            user_id,
            self.failure_cooldown(),
            exempt=exempt,
        )
        return max(success_remaining, failure_remaining)

    def penalize_success(self, user_id: int) -> None:
        penalize_user_rate_limit(
            self.success_namespace,
            user_id,
            self.success_cooldown(),
            exempt=is_superuser(user_id),
        )

    def penalize_failure(self, user_id: int) -> None:
        penalize_user_rate_limit(
            self.failure_namespace,
            user_id,
            self.failure_cooldown(),
            exempt=is_superuser(user_id),
        )
