# SPDX-License-Identifier: MIT
"""Framework-independent binding to the pinned upstream litehtml binary."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from functools import cache
from importlib.metadata import distribution
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import urljoin

NATIVE_DISTRIBUTION = "ironsbot-litehtml-core"
NATIVE_VERSION = "0.1.0rc5"
SOURCE_PATH = Path(__file__).parent
logger = logging.getLogger(__name__)

ImageFetcher = Callable[[str], Coroutine[Any, Any, bytes | None]]
CssFetcher = Callable[[str], Coroutine[Any, Any, str | None]]


class _NativeCore(Protocol):
    _init_fontconfig_internal: Callable[[], None]
    _render_internal: Callable[..., Awaitable[bytes]]


@cache
def _native_core() -> _NativeCore:
    """Load only the compiled ABI, never execute the upstream plugin package."""

    package = distribution(NATIVE_DISTRIBUTION)
    if package.version != NATIVE_VERSION:
        msg = "the native HTML renderer does not match the pinned ABI version"
        raise RuntimeError(msg)
    candidates = tuple(
        package.locate_file(item)
        for item in package.files or ()
        if item.as_posix().startswith("ironsbot_litehtml/core")
        and item.suffix in {".pyd", ".so"}
    )
    if len(candidates) != 1:
        msg = "the native HTML renderer binary is missing or ambiguous"
        raise RuntimeError(msg)
    spec = spec_from_file_location(__name__ + ".core", str(candidates[0]))
    if spec is None or spec.loader is None:
        msg = "the native HTML renderer binary cannot be loaded"
        raise RuntimeError(msg)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_NativeCore", module)


def initialize_fontconfig() -> None:
    """Initialize native fonts using the process FONTCONFIG/FC environment."""

    _native_core()._init_fontconfig_internal()


async def render_html(  # noqa: PLR0913 - exact render options and explicit resource ports
    html: str,
    *,
    base_url: str,
    max_width: int,
    allow_refit: bool,
    img_fetch_fn: ImageFetcher,
    css_fetch_fn: CssFetcher,
) -> bytes:
    """Preserve the existing template renderer's native options exactly."""

    def native_error(kind: type[BaseException], *_details: object) -> None:
        logger.error("native HTML resource callback failed: %s", kind.__name__)

    native_data_scheme = True
    debug = False
    return await _native_core()._render_internal(
        html,
        base_url,
        96.0,
        max_width,
        600.0,
        12.0,
        "sans-serif",
        allow_refit,
        -1,
        "zh",
        "CN",
        native_error,
        asyncio.run_coroutine_threadsafe,
        urljoin,
        asyncio.get_running_loop(),
        img_fetch_fn,
        css_fetch_fn,
        native_data_scheme,
        debug,
    )
