# SPDX-License-Identifier: MIT
"""Generic optional actions contributed to a player's detail conversation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.services.seer.query_result import QueryReply

if TYPE_CHECKING:
    from ironsbot.core.semantic_requests import ActionDefinition

PlayerDetailActionQuery = Callable[[int, int, int | None], Awaitable[QueryReply]]
_BUILTIN_ALIASES = frozenset({"收集", "巅峰", "群星牌"})


@dataclass(frozen=True, slots=True)
class PlayerDetailExtensionAction:
    """One optional action shown after built-in player detail items."""

    id: str
    feature: str
    label: str
    aliases: tuple[str, ...]
    command_help_id: str
    query: PlayerDetailActionQuery
    action: ActionDefinition


class PlayerDetailExtensionRegistry:
    """Process-local registry populated by installed optional extensions."""

    def __init__(self) -> None:
        self._actions: dict[str, PlayerDetailExtensionAction] = {}

    def register(self, action: PlayerDetailExtensionAction) -> None:
        label = action.label.strip()
        if (
            not action.id
            or not action.feature
            or not label
            or not action.command_help_id.strip()
        ):
            msg = (
                "player detail extension action requires id, feature, label, "
                "and command_help_id"
            )
            raise ValueError(msg)
        if "【" in label or "】" in label:
            msg = "player detail extension labels must not include menu brackets"
            raise ValueError(msg)
        aliases = tuple(_normalize_command(alias) for alias in action.aliases)
        if not aliases or any(not alias for alias in aliases):
            msg = "player detail extension action requires aliases"
            raise ValueError(msg)
        if any(alias.isdecimal() for alias in aliases):
            msg = "player detail extension aliases must not declare menu numbers"
            raise ValueError(msg)
        builtin_overlap = sorted(set(aliases) & _BUILTIN_ALIASES)
        if builtin_overlap:
            msg = "player detail extension aliases overlap built-ins: " + ", ".join(
                builtin_overlap
            )
            raise ValueError(msg)
        if len(set(aliases)) != len(aliases):
            msg = f"player detail extension repeats an alias: {action.id}"
            raise ValueError(msg)
        if action.id in self._actions:
            msg = f"player detail extension repeats an id: {action.id}"
            raise ValueError(msg)
        claimed = {
            alias
            for current in self._actions.values()
            for alias in current.aliases
        }
        overlap = sorted(set(aliases) & claimed)
        if overlap:
            msg = "player detail extension alias collision: " + ", ".join(overlap)
            raise ValueError(msg)
        if action.action.id != action.id:
            msg = "player detail extension action id must match its registration id"
            raise ValueError(msg)
        self._actions[action.id] = PlayerDetailExtensionAction(
            id=action.id,
            feature=action.feature,
            label=label,
            aliases=aliases,
            command_help_id=action.command_help_id.strip(),
            query=action.query,
            action=action.action,
        )

    def actions(self) -> tuple[PlayerDetailExtensionAction, ...]:
        return tuple(self._actions.values())

    def get(self, action_id: str) -> PlayerDetailExtensionAction | None:
        return self._actions.get(action_id)

    def resolve_alias(
        self,
        text: str,
        *,
        allowed_ids: Iterable[str],
    ) -> PlayerDetailExtensionAction | None:
        alias = _normalize_command(text)
        for action_id in allowed_ids:
            action = self._actions.get(action_id)
            if action is not None and alias in action.aliases:
                return action
        return None

    def resolve_direct_command(
        self,
        text: str,
    ) -> tuple[PlayerDetailExtensionAction, str] | None:
        """Resolve an extension action and its optional player reference.

        Direct command parsing stays in the public runtime so extensions only
        receive a validated numeric player ID when their query is invoked.
        """

        normalized = _normalize_command(text)
        matches = sorted(
            (
                (alias, action)
                for action in self._actions.values()
                for alias in action.aliases
                if normalized.startswith(alias)
            ),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        if not matches:
            return None
        alias, action = matches[0]
        return action, normalized[len(alias) :]


def _normalize_command(value: str) -> str:
    return "".join(value.split()).casefold()
