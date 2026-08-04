# SPDX-License-Identifier: MIT
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.integrations.seer_data import pet_info_renderer
from ironsbot.services.seer.rendering.pet_info_models import (
    PetCoreSnapshot,
    PetDerivedDisplayData,
    PetInfoSnapshot,
    PetStatsSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


class FakeData:
    def __init__(self) -> None:
        self.session_active = False

    @contextmanager
    def query(self, operation: object) -> Iterator[PetInfoSnapshot | None]:
        self.session_active = True
        try:
            yield operation(object())  # type: ignore[operator]
        finally:
            self.session_active = False


class FakeImages:
    def __init__(self, data: FakeData) -> None:
        self._data = data

    async def fetch(self, *_args: object, **_kwargs: object) -> bytes:
        assert self._data.session_active is False
        return b"image"


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def get(self, category: str, content_key: str) -> bytes | None:
        return self.values.get((category, content_key))

    def put(self, category: str, content_key: str, data: bytes) -> None:
        self.values[(category, content_key)] = data


def _snapshot() -> PetInfoSnapshot:
    return PetInfoSnapshot(
        pet=PetCoreSnapshot(1, "测试精灵", 1001, 0, 1, "普通", ""),
        base_stats=PetStatsSnapshot(1, 1, 1, 1, 1, 1),
        advance_stats=None,
        skills=(),
        soulmarks=(),
        activation_items=(),
        partner=None,
        skill_mintmarks=(),
        display=PetDerivedDisplayData((), (), ()),
        rich_texts=(),
    )


@pytest.mark.asyncio
async def test_render_adapter_closes_sql_session_before_fetching_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = FakeData()
    cache = FakeCache()
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        pet_info_renderer,
        "load_pet_info_snapshot",
        lambda _session, _pet_id: _snapshot(),
    )
    monkeypatch.setattr(pet_info_renderer, "_load_gender_icon", lambda _gender: b"x")

    async def render_html(**kwargs: Any) -> bytes:
        assert data.session_active is False
        captured.update(kwargs)
        return b"rendered"

    result = await pet_info_renderer.render_published_pet_info(
        cast("RenderCache", cache),
        cast("SeerDataAccess", data),
        cast("SeerImageSource", FakeImages(data)),
        cast("HtmlTemplateRenderer", render_html),
        1,
    )

    assert result == b"rendered"
    assert captured["templates"]["pet_id"] == 1
    assert cache.values
