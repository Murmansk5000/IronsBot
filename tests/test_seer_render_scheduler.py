from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from ironsbot.services.seer.render_scheduler import RenderScheduler

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from ironsbot.services.seer.rendering import TemplatePath


@pytest.mark.asyncio
async def test_render_scheduler_limits_same_resource_without_blocking_other_tasks(
) -> None:
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

    scheduler = RenderScheduler(renderer, max_concurrent=1)
    first = asyncio.create_task(scheduler.render("", "first", {}))
    await first_started.wait()
    second = asyncio.create_task(scheduler.render("", "second", {}))

    await asyncio.sleep(0)
    assert not second_started.is_set()

    unrelated_work = asyncio.Event()
    unrelated_work.set()
    await unrelated_work.wait()
    assert not second_started.is_set()

    release_first.set()
    assert await first == b"first"
    assert await second == b"second"
    assert peak_active == 1


@pytest.mark.asyncio
async def test_render_scheduler_allows_configured_parallel_renders() -> None:
    parallel_limit = 2
    both_started = asyncio.Event()
    release = asyncio.Event()
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
        del template_path, template_name, templates, max_width, allow_refit
        active += 1
        peak_active = max(peak_active, active)
        if active == parallel_limit:
            both_started.set()
        await release.wait()
        active -= 1
        return b"image"

    scheduler = RenderScheduler(renderer, max_concurrent=parallel_limit)
    tasks = [
        asyncio.create_task(scheduler.render("", "one", {})),
        asyncio.create_task(scheduler.render("", "two", {})),
    ]
    await both_started.wait()
    release.set()

    assert await asyncio.gather(*tasks) == [b"image", b"image"]
    assert peak_active == parallel_limit
