from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ironsbot.services.seer.render_coordinator import RenderCoordinator

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from ironsbot.services.seer.rendering import TemplatePath


@pytest.mark.asyncio
async def test_render_coordinator_serializes_native_renders() -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    active = 0
    peak_active = 0

    async def renderer(
        template_path: TemplatePath,
        template_name: str,
        templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        nonlocal active, peak_active
        del template_path, templates, max_width, allow_refit
        active += 1
        peak_active = max(peak_active, active)
        if template_name == "first":
            first_started.set()
            await release_first.wait()
        else:
            second_started.set()
        active -= 1
        return template_name.encode()

    coordinator = RenderCoordinator(renderer, timeout_seconds=10)
    first = asyncio.create_task(coordinator.render("", "first", {}))
    await first_started.wait()
    second = asyncio.create_task(coordinator.render("", "second", {}))

    await asyncio.sleep(0)
    assert not second_started.is_set()

    release_first.set()
    assert await first == b"first"
    assert await second == b"second"
    assert peak_active == 1


@pytest.mark.asyncio
async def test_render_coordinator_enforces_native_timeout() -> None:
    started = asyncio.Event()

    async def renderer(
        _template_path: TemplatePath,
        _template_name: str,
        _templates: Mapping[Any, Any],
        *,
        max_width: int = 500,
        allow_refit: bool = True,
    ) -> bytes:
        del max_width, allow_refit
        started.set()
        await asyncio.Event().wait()
        return b"unreachable"

    coordinator = RenderCoordinator(renderer, timeout_seconds=0.01)

    with pytest.raises(asyncio.TimeoutError):
        await coordinator.render("", "slow", {})
    assert started.is_set()
