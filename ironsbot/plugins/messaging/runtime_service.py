from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol, TypeVar

from ironsbot.shared.command_text import command_text_matches

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

ActionT = TypeVar("ActionT", bound="CommandAction")


class CommandAction(Protocol):
    enabled: bool
    commands: list[str]


class ScheduledAction(Protocol):
    hour: int
    minute: int
    day_of_week: str | None


def build_schedule_job_id(prefix: str, index: int, raw_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw_id or f"task_{index}")
    safe_id = safe_id.strip("_") or str(index)
    return f"message_action_{prefix}_{safe_id}"


def build_schedule_trigger_kwargs(task: ScheduledAction) -> dict[str, int | str]:
    trigger_kwargs: dict[str, int | str] = {
        "hour": task.hour,
        "minute": task.minute,
        "second": 0,
    }
    if task.day_of_week:
        trigger_kwargs["day_of_week"] = task.day_of_week
    return trigger_kwargs


def find_command_action(
    text: str,
    actions: Iterable[ActionT],
    *,
    is_allowed: Callable[[ActionT], bool],
) -> ActionT | None:
    for action in actions:
        if not action.enabled or not is_allowed(action):
            continue
        if command_text_matches(text, action.commands):
            return action
    return None
