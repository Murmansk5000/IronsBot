# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Callable
from typing import Any

_state: dict[str, Callable[[], Any] | None] = {"game_client_getter": None}


class GameClientGetterNotRegisteredError(RuntimeError):
    """Raised when the headless Seer client provider is not registered."""


def register_game_client_getter(getter: Callable[[], Any]) -> None:
    _state["game_client_getter"] = getter


def get_game_client() -> Any:
    getter = _state["game_client_getter"]
    if getter is None:
        raise GameClientGetterNotRegisteredError
    return getter()
