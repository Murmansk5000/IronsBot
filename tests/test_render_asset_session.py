from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from ironsbot.services.seer.images import (
    ImageSourceError,
    MissingImageRepositoryError,
    placeholder_image,
    validate_image_data,
)
from ironsbot.services.seer.render_assets import RenderAssetSession
from ironsbot.services.seer.render_cache import RenderCacheEntry
from ironsbot.services.seer.render_pipeline import RenderExecution, current_render

if TYPE_CHECKING:
    from ironsbot.services.seer.images import ImageKind


@pytest.mark.asyncio
async def test_failure_keeps_other_assets_and_prevents_final_cache() -> None:
    real = placeholder_image("pet_head")

    class Source:
        async def fetch(
            self, kind: ImageKind, key: str, *, fallback: bool = True
        ) -> bytes:
            del kind
            assert not fallback
            if key == "missing":
                raise ImageSourceError("offline")
            return real

    put = Mock()
    cache = Mock(entry=Mock(return_value=RenderCacheEntry(lambda: None, put)))
    scope = RenderAssetSession(Source(), cache)
    entry = scope.entry("vote", "test")
    healthy, missing = await asyncio.gather(
        scope.fetch("pet_head", "healthy"),
        scope.fetch("element_type", "missing"),
    )
    assert healthy is real
    validate_image_data(missing)
    assert not scope.complete
    assert tuple(scope.failures) == (("element_type", "missing"),)
    entry.put(b"incomplete-result")
    put.assert_not_called()


@pytest.mark.asyncio
async def test_next_session_retries_and_can_cache_recovered_result() -> None:
    class Source:
        attempts = 0

        async def fetch(
            self, kind: ImageKind, key: str, *, fallback: bool = True
        ) -> bytes:
            del key, fallback
            self.attempts += 1
            if self.attempts == 1:
                raise ImageSourceError("temporary")
            return placeholder_image(kind)

    source = Source()
    put = Mock()
    cache = Mock(entry=Mock(return_value=RenderCacheEntry(lambda: None, put)))
    first = RenderAssetSession(source, cache)
    await first.fetch("pet_head", "1")
    first.entry("vote", "1").put(b"bad")
    second = RenderAssetSession(source, cache)
    await second.fetch("pet_head", "1")
    second.entry("vote", "1").put(b"good")
    assert second.complete
    assert source.attempts == len((first, second))
    put.assert_called_once_with(b"good")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        asyncio.CancelledError(),
        MissingImageRepositoryError("pet_head"),
        RuntimeError("data error"),
    ],
)
async def test_non_asset_failure_is_not_disguised(error: BaseException) -> None:
    class Source:
        async def fetch(
            self, kind: ImageKind, key: str, *, fallback: bool = True
        ) -> bytes:
            del kind, key, fallback
            raise error

    scope = RenderAssetSession(Source(), Mock())
    with pytest.raises(type(error)):
        await scope.fetch("pet_head", "1")
    assert scope.complete


def test_invalid_image_is_rejected() -> None:
    with pytest.raises(ImageSourceError):
        validate_image_data(b"not an image")


@pytest.mark.asyncio
@pytest.mark.parametrize("alternative_valid", [True, False])
async def test_authoritative_alternative_controls_final_quality(
    *, alternative_valid: bool
) -> None:
    class Source:
        async def fetch(
            self, kind: ImageKind, key: str, *, fallback: bool = True
        ) -> bytes:
            del kind, key, fallback
            raise ImageSourceError("404")

    png = placeholder_image("soulmark_icon")
    put = Mock()
    scope = RenderAssetSession(
        Source(), Mock(entry=Mock(return_value=RenderCacheEntry(lambda: None, put)))
    )
    execution = RenderExecution()
    token = current_render.set(execution)
    try:
        data = await scope.fetch_with_alternative(
            "soulmark_icon", "2149", alternative=png if alternative_valid else b"bad"
        )
        validate_image_data(data)
        assert scope.complete is alternative_valid
        assert execution.degraded is (not alternative_valid)
        scope.entry("pet_info", "4950").put(b"rendered")
        assert bool(execution.writes) is alternative_valid
    finally:
        current_render.reset(token)
