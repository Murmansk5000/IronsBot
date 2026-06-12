# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


class _NoOpMatcher:
    def handle(
        self,
        *_: Any,
        **__: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return _decorator


class _NoOpMatcherGroup:
    def on_message(self, *_: Any, **__: Any) -> _NoOpMatcher:
        return _NoOpMatcher()

    def on_fullmatch(self, *_: Any, **__: Any) -> _NoOpMatcher:
        return _NoOpMatcher()

    def on_command(self, *_: Any, **__: Any) -> _NoOpMatcher:
        return _NoOpMatcher()


matcher_group = _NoOpMatcherGroup()
