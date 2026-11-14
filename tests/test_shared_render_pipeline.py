from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from ironsbot.services.seer import image_failure_notice
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.images import ImageKind, ImageSourceError, placeholder_image
from ironsbot.services.seer.render_assets import RenderAssetSession
from ironsbot.services.seer.render_cache import RenderCacheEntry
from ironsbot.services.seer.render_coordinator import RenderCoordinator
from ironsbot.services.seer.render_pipeline import (
    RenderRequest,
    mark_render_degraded,
    publish_render_cache,
)


async def _renderer(*_args: Any, **_kwargs: Any) -> bytes:
    return b"png"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["raise", "timeout"])
async def test_failure_notice_cannot_block_partial_image(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_failure_notice, "_REPORT_TIMEOUT_SECONDS", 0.001)

    async def reporter(_kind: str, _key: str, _error: ImageSourceError) -> None:
        if mode == "raise":
            msg = "notice unavailable"
            raise RuntimeError(msg)
        await asyncio.Event().wait()

    await image_failure_notice.report_render_asset_failures(
        reporter, (("pet_head", "fictional", ImageSourceError("offline")),), None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("degraded", [False, True])
async def test_pipeline_commits_only_complete_images(*, degraded: bool) -> None:
    writes: list[bytes] = []
    coordinator = RenderCoordinator(_renderer, 1)

    async def prepare() -> bytes:
        publish_render_cache(lambda: writes.append(b"png"))
        if degraded:
            mark_render_degraded()
        return await coordinator.render("", "test", {})

    result = await coordinator.execute(RenderRequest("test", "known data"), prepare)
    assert result.status == ("degraded" if degraded else "complete")
    assert result.image == b"png"
    assert writes == ([] if degraded else [b"png"])


@pytest.mark.asyncio
async def test_preparation_timeout_preserves_text_and_discards_writes() -> None:
    writes: list[bool] = []

    async def prepare() -> bytes:
        publish_render_cache(lambda: writes.append(True))
        await asyncio.Event().wait()
        return b"late"

    result = await RenderCoordinator(_renderer, 0.01).execute(
        RenderRequest("weekly", "verified choices"), prepare
    )
    assert result.status == "failed"
    assert result.failure_stage == "prepare"
    assert "verified choices" in result.fallback_text
    assert not writes


@pytest.mark.asyncio
async def test_queue_timeout_does_not_enter_renderer() -> None:
    coordinator = RenderCoordinator(_renderer, 0.01)
    await coordinator._semaphore.acquire()
    try:
        result = await coordinator.execute(
            RenderRequest("queued"), lambda: coordinator.render("", "queued", {})
        )
        assert result.failure_stage == "queue"
    finally:
        coordinator._semaphore.release()
    assert await coordinator.render("", "recovered", {}) == b"png"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [ValueError("bad template"), RuntimeError("bad layout")]
)
async def test_template_errors_become_typed_failures(error: Exception) -> None:
    async def renderer(*_args: Any, **_kwargs: Any) -> bytes:
        raise error

    result = await RenderCoordinator(renderer, 1).execute(
        RenderRequest("test"),
        lambda: RenderCoordinator(renderer, 1).renderer("", "", {}),
    )
    assert result.status == "failed"
    assert result.exception_type == type(error).__name__


@pytest.mark.asyncio
async def test_data_errors_and_cancellation_are_not_image_failures() -> None:
    coordinator = RenderCoordinator(_renderer, 1)

    async def missing() -> bytes:
        raise DataUnavailableError

    with pytest.raises(DataUnavailableError):
        await coordinator.execute(RenderRequest("test"), missing)

    async def cancelled() -> bytes:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await coordinator.execute(RenderRequest("test"), cancelled)


@pytest.mark.asyncio
async def test_empty_image_is_failed_and_never_published() -> None:
    writes: list[bool] = []

    async def empty() -> bytes:
        publish_render_cache(lambda: writes.append(True))
        return b""

    result = await RenderCoordinator(_renderer, 1).execute(
        RenderRequest("empty"), empty
    )
    assert result.status == "failed"
    assert not writes


@pytest.mark.asyncio
async def test_concurrent_render_quality_is_not_shared() -> None:
    arrived = asyncio.Event()
    release = asyncio.Event()
    coordinator = RenderCoordinator(_renderer, 1)

    async def degraded() -> bytes:
        mark_render_degraded()
        arrived.set()
        await release.wait()
        return b"degraded"

    first = asyncio.create_task(coordinator.execute(RenderRequest("first"), degraded))
    await arrived.wait()

    async def healthy() -> bytes:
        return b"complete"

    second = await coordinator.execute(RenderRequest("second"), healthy)
    release.set()
    assert (await first).status == "degraded"
    assert second.status == "complete"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "invalid", "offline"])
async def test_bad_assets_degrade_only_their_position_and_do_not_cache(
    mode: str,
) -> None:
    good = placeholder_image("pet_head")

    class Source:
        async def fetch(
            self, kind: ImageKind, key: str, *, fallback: bool = True
        ) -> bytes:
            del kind, fallback
            if key == "good":
                return good
            if mode == "timeout":
                await asyncio.Event().wait()
            if mode == "offline":
                raise ImageSourceError("offline")
            return b"corrupt"

    put = Mock()
    scope = RenderAssetSession(
        Source(),
        Mock(entry=Mock(return_value=RenderCacheEntry(lambda: None, put))),
        timeout_seconds=0.001,
    )

    async def prepare() -> bytes:
        real, missing = await asyncio.gather(
            scope.fetch("pet_head", "good"), scope.fetch("pet_head", "bad")
        )
        assert real == good
        assert missing == placeholder_image("pet_head")
        scope.entry("new_content", "test").put(b"degraded")
        return b"degraded"

    result = await RenderCoordinator(_renderer, 1).execute(
        RenderRequest("test"), prepare
    )
    assert result.status == "degraded"
    assert tuple(scope.failures) == (("pet_head", "bad"),)
    put.assert_not_called()


def test_native_template_binding_has_one_composition_owner() -> None:
    root = Path(__file__).resolve().parents[1] / "ironsbot"
    owners = []
    # These are the only packages allowed to compose or call the native port.
    for package in ("app", "services", "extensions"):
        for path in (root / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            owners.extend(
                path.relative_to(root).as_posix()
                for node in ast.walk(tree)
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "ironsbot.integrations.htmlkit"
                    and any(
                        alias.name == "render_html_template" for alias in node.names
                    )
                )
            )
    assert owners == ["app/rendering_composition.py"]


def test_builtin_template_ports_are_guarded() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "ironsbot/app/seer_composition.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    guarded = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "guard"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert guarded == {
        "pet_info",
        "type_matchup",
        "peak_pool",
        "peak_pool_vote",
        "peak_pet_rank",
        "lucky_skin_window",
        "player_lineup",
        "new_content",
    }
