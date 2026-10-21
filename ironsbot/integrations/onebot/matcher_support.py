# SPDX-License-Identifier: MIT
"""Callback binding helpers for OneBot dependency parsing."""

from __future__ import annotations

from functools import partial
from inspect import Signature, signature
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


T = TypeVar("T")
EXPLICIT_COMMAND_STATE_KEY = "_ironsbot_explicit_command"


class _BoundPartial(partial):
    @property
    def __globals__(self) -> dict[str, Any]:
        """Expose wrapped globals for NoneBot dependency parsing."""

        return cast("dict[str, Any]", getattr(self.func, "__globals__", {}))

    @property
    def __signature__(self) -> Signature:
        """Hide arguments supplied by application composition."""

        original = signature(self.func)
        try:
            supplied = original.bind_partial(*self.args, **(self.keywords or {}))
        except TypeError:
            return original
        return original.replace(
            parameters=[
                parameter
                for name, parameter in original.parameters.items()
                if name not in supplied.arguments
            ]
        )


class _AsyncPartial(_BoundPartial):
    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        result: Awaitable[Any] = super().__call__(*args, **kwargs)
        return await result


def bind(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> Callable[..., T]:
    """Bind a synchronous callback without hiding its annotations."""

    return cast("Callable[..., T]", _BoundPartial(func, *args, **kwargs))


def bind_async(
    func: Callable[..., Awaitable[T]], /, *args: Any, **kwargs: Any
) -> Callable[..., Awaitable[T]]:
    """Bind asynchronous callbacks while preserving their awaitable signature."""

    return cast("Callable[..., Awaitable[T]]", _AsyncPartial(func, *args, **kwargs))
