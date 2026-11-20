from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.integrations.bilibili_image_diff import compare_images
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.services.bilibili.edit_rendering import BiliEditRenderer
from ironsbot.services.bilibili.target_models import BiliPushTargets
from ironsbot.services.messaging.image_collage import ImageCollageError
from ironsbot.services.seer.render_coordinator import RenderCoordinator
from tests.test_bilibili_conversation_queue import drain
from tests.test_bilibili_edit_delivery import edited
from tests.test_bilibili_edit_images import picture
from tests.test_bilibili_revisions import UID, item

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_old_404_uses_exact_frozen_bytes_and_compares_only_changed_region(
    tmp_path: Path,
) -> None:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    ledger.prepare(item(), 1, UID, BiliPushTargets([], [], [], []), ())
    ledger.freeze_media(
        "123456", OutboundMessage((BinaryImagePart(picture(), "image/png", "old.png"),))
    )
    owner, calls = TaskOwner(), []

    async def render(
        _path: object, _name: str, values: dict, **_kwargs: object
    ) -> bytes:
        calls.append(values)
        return picture()

    fetch = AsyncMock(return_value=picture(changed=True))
    collage = cast(
        "Any",
        type(
            "Collage",
            (),
            {
                "fetch_image": fetch,
                "max_source_bytes": 20_000_000,
                "inspect_animation": None,
            },
        )(),
    )
    renderer = BiliEditRenderer(
        RenderCoordinator(cast("Any", render), 5),
        ledger,
        collage,
        compare_images,
        owner.create,
    )
    result = await renderer.media(edited(text=False, media=True))
    await drain(owner)
    assert result is not None and isinstance(result.parts[0], BinaryImagePart)
    assert fetch.await_count == 1
    assert "局部" in calls[0]["rows"][0]["note"]
    assert calls[0]["rows"][0]["before"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_public_render_failure_returns_truthful_body_fallback(
    tmp_path: Path,
) -> None:
    async def fail(*_args: object, **_kwargs: object) -> bytes:
        raise RuntimeError

    owner = TaskOwner()
    renderer = BiliEditRenderer(
        RenderCoordinator(cast("Any", fail), 5),
        SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite"),
        cast("Any", object()),
        compare_images,
        owner.create,
    )
    result = await renderer.text(edited())
    assert result is not None and isinstance(result.parts[0], TextPart)
    assert "修改前" in result.parts[0].text and "修改后" in result.parts[0].text


@pytest.mark.asyncio
async def test_missing_old_image_keeps_new_image_and_explicit_label(
    tmp_path: Path,
) -> None:
    captured = []

    async def render(
        _path: object, _name: str, values: dict, **_kwargs: object
    ) -> bytes:
        captured.append(values)
        return picture()

    async def fetch(url: str, _limit: int) -> bytes:
        if "old.jpg" in url:
            raise ImageCollageError.download_failed()
        return picture(changed=True)

    owner = TaskOwner()
    collage = cast(
        "Any",
        type(
            "Collage",
            (),
            {
                "fetch_image": staticmethod(fetch),
                "max_source_bytes": 20_000_000,
                "inspect_animation": None,
            },
        )(),
    )
    renderer = BiliEditRenderer(
        RenderCoordinator(cast("Any", render), 5),
        SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite"),
        collage,
        compare_images,
        owner.create,
    )
    result = await renderer.media(edited(text=False, media=True))
    await drain(owner)
    assert result is not None and isinstance(result.parts[0], BinaryImagePart)
    row = captured[0]["rows"][0]
    assert not row["before"] and row["after"]
    assert "旧图不可用" in row["before_missing"]
