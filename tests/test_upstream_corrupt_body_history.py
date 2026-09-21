# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64
from dataclasses import replace
from io import BytesIO
from typing import TYPE_CHECKING, Any, cast

import pytest
from PIL import Image

from ironsbot.integrations.seer_data import pet_info_renderer
from ironsbot.services.seer.images import ImageSourceError
from ironsbot.services.seer.pet_info_views import PetSkillSnapshot
from tests.test_seer_pet_info_render_adapter import FakeCache, FakeData, _snapshot

if TYPE_CHECKING:
    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource
    from ironsbot.services.seer.render_cache import RenderCache
    from ironsbot.services.seer.rendering import HtmlTemplateRenderer


def _body_png() -> bytes:
    with Image.new("RGBA", (2, 1)) as image:
        image.putpixel((0, 0), (255, 0, 0, 64))
        image.putpixel((1, 0), (0, 0, 255, 192))
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt_body", [None, b"invalid", _body_png()[:45]])
async def test_corrupt_body_is_local_failure_not_whole_render_failure(
    monkeypatch: pytest.MonkeyPatch, corrupt_body: bytes | None
) -> None:
    data, cache = FakeData(), FakeCache()
    snapshot = replace(
        _snapshot(),
        skills=(
            PetSkillSnapshot(
                id=10,
                name="保留技能",
                type_id=1,
                type_name="普通",
                category_id=1,
                category_name="物理",
                power=80,
                max_pp=10,
                accuracy=100,
                crit_rate=None,
                priority=0,
                must_hit=False,
                info=None,
                learning_level=1,
                is_special=False,
                is_advanced=False,
                is_fifth=False,
                effects=(),
                friend_effects=(),
                activation_item_id=None,
                hide_effect_description=None,
            ),
        ),
    )
    monkeypatch.setattr(
        pet_info_renderer, "load_pet_info_snapshot", lambda *_: snapshot
    )
    head = _body_png()

    class Images:
        async def fetch(self, kind: str, _key: str, *, fallback: bool) -> bytes:
            assert fallback is False
            if kind == "pet_body":
                if corrupt_body is None:
                    raise ImageSourceError
                return corrupt_body
            return head

    captured: dict[str, Any] = {}
    failures: list[tuple[str, str, ImageSourceError]] = []

    async def render_html(**kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"rendered-with-placeholder"

    async def report(kind: str, key: str, error: ImageSourceError) -> None:
        failures.append((kind, key, error))

    result = await pet_info_renderer.render_published_pet_info(
        cast("RenderCache", cache),
        cast("SeerDataAccess", data),
        cast("SeerImageSource", Images()),
        cast("HtmlTemplateRenderer", render_html),
        1,
        image_failure_reporter=report,
    )
    assert result == b"rendered-with-placeholder"
    assert base64.b64decode(
        captured["pet_body_img"].split(",", 1)[1]
    ) == pet_info_renderer.placeholder_image("pet_body")
    assert base64.b64decode(captured["pet_head_img"].split(",", 1)[1]) == head
    assert captured["level_skills"][0]["name"] == "保留技能"
    assert len(failures) == 1
    assert failures[0][:2] == ("pet_body", "1001")
    if corrupt_body is not None:
        assert isinstance(failures[0][2].__cause__, OSError)
    assert not cache.values
