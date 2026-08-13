# SPDX-License-Identifier: MIT
"""NoneBot-safe callback binding helpers."""

from __future__ import annotations

from functools import partial
from inspect import Signature, signature
from typing import TYPE_CHECKING, Any, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")


class _BoundPartial(partial):
    @property
    def __globals__(self) -> dict[str, Any]:
        """Expose the wrapped function globals for NoneBot dependency parsing."""

        return cast("dict[str, Any]", getattr(self.func, "__globals__", {}))

    @property
    def __signature__(self) -> Signature:
        """Hide arguments already supplied by the application runtime."""

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


def bind(
    func: Callable[..., T],
    /,
    *args: Any,
    **kwargs: Any,
) -> Callable[..., T]:
    """Bind a synchronous NoneBot callback without hiding its annotations."""

    return cast("Callable[..., T]", _BoundPartial(func, *args, **kwargs))


def bind_async(
    func: Callable[..., Awaitable[T]],
    /,
    *args: Any,
    **kwargs: Any,
) -> Callable[..., Awaitable[T]]:
    """Bind arguments while keeping the callable visibly asynchronous."""

    return cast(
        "Callable[..., Awaitable[T]]",
        _AsyncPartial(func, *args, **kwargs),
    )
