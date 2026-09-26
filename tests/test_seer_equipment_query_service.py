from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from ironsbot.integrations.http.clients import HttpClients
from ironsbot.integrations.http.seer_images import HttpSeerImageSource
from ironsbot.services.seer.equipment import EquipmentQueryService
from ironsbot.services.seer.images import (
    PublishedAssetRepository,
    PublishedRenderAssetSnapshot,
)

NOT_FOUND_IMAGE_ERROR = "404 Not Found"
CONNECTION_FAILED = "connection failed"

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.seer.data import SeerDataAccess
    from ironsbot.services.seer.images import SeerImageSource


class FakeData:
    suit = object()
    equip = object()
    title = object()

    def __init__(self) -> None:
        self.values: dict[object, tuple[Any, ...]] = {}
        self.session_active = False

    @contextmanager
    def resolve(
        self,
        getter: object,
        _arg: str,
    ) -> Iterator[tuple[Any, ...]]:
        self.session_active = True
        try:
            yield self.values.get(getter, ())
        finally:
            self.session_active = False

    @contextmanager
    def get(self, getter: object, item_id: int) -> Iterator[Any | None]:
        self.session_active = True
        try:
            yield next(
                (
                    item
                    for item in self.values.get(getter, ())
                    if int(item.id) == item_id
                ),
                None,
            )
        finally:
            self.session_active = False


class FakeImages:
    async def fetch(
        self,
        _kind: object,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        assert fallback is False
        return f"image:{key}".encode()


class MissingImages:
    async def fetch(
        self,
        _kind: object,
        _key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        from ironsbot.services.seer.images import ImageSourceStatusError

        assert fallback is False
        raise ImageSourceStatusError(404, "Not Found")


def _service(
    data: FakeData,
    images: object | None = None,
) -> EquipmentQueryService:
    return EquipmentQueryService(
        cast("SeerDataAccess", data),
        cast("SeerImageSource", images or FakeImages()),
    )


class SessionBoundSuit:
    id = 1
    name = "勇者套装"

    def __init__(self, data: FakeData) -> None:
        self._data = data

    @property
    def equips(self) -> list[Any]:
        assert self._data.session_active
        return [
            SimpleNamespace(
                id=11,
                name="头盔",
                part_type=SimpleNamespace(id=0),
                bonus=SimpleNamespace(desc="攻击 + 5"),
            )
        ]

    @property
    def bonus(self) -> Any:
        assert self._data.session_active
        return SimpleNamespace(desc="全属性 + 10")


@pytest.mark.asyncio
async def test_title_query_returns_rendered_reply() -> None:
    data = FakeData()
    data.values[data.title] = (
        SimpleNamespace(
            id=7,
            name="星际英雄",
            ability_desc="体力 + 20",
            achievement=SimpleNamespace(point=10),
        ),
    )

    result = await _service(data).search("title", "星际英雄")

    assert result.reply is not None
    assert result.reply.text == ("【星际英雄】\n🆔：7\n成就点数：10点\n效果：体力 + 20")
    assert result.reply.image == b"image:7"


@pytest.mark.asyncio
async def test_title_without_achievement_omits_points() -> None:
    data = FakeData()
    data.values[data.title] = (
        SimpleNamespace(
            id=8,
            name="普通称号",
            ability_desc="",
            achievement=None,
        ),
    )

    result = await _service(data).search("title", "普通称号")

    assert result.reply is not None
    assert result.reply.text == "【普通称号】\n🆔：8"


@pytest.mark.asyncio
async def test_equipment_query_returns_choices_for_multiple_matches() -> None:
    data = FakeData()
    data.values[data.suit] = (
        SimpleNamespace(id=1, name="套装一"),
        SimpleNamespace(id=2, name="套装二"),
    )

    result = await _service(data).search("suit", "套装")

    assert [choice.value for choice in result.choices] == [1, 2]


@pytest.mark.asyncio
async def test_suit_selection_returns_parts_and_bonus() -> None:
    data = FakeData()
    part_type = SimpleNamespace(id=0)
    equip = SimpleNamespace(
        id=11,
        name="头盔",
        part_type=part_type,
        bonus=SimpleNamespace(desc="攻击 + 5"),
    )
    data.values[data.suit] = (
        SimpleNamespace(
            id=1,
            name="勇者套装",
            equips=[equip],
            bonus=SimpleNamespace(desc="全属性 + 10"),
        ),
    )

    result = await _service(data).select("suit", 1)

    assert result.reply is not None
    assert "头部：头盔（11）" in result.reply.text
    assert "套装效果：全属性 + 10" in result.reply.text


@pytest.mark.asyncio
async def test_equipment_formats_relationships_before_session_closes() -> None:
    data = FakeData()
    data.values[data.suit] = (SessionBoundSuit(data),)

    result = await _service(data).select("suit", 1)

    assert result.reply is not None
    assert "头部：头盔（11）" in result.reply.text
    assert data.session_active is False


@pytest.mark.asyncio
async def test_equipment_selection_reports_missing_item() -> None:
    result = await _service(FakeData()).select("equip", 99)

    assert result.message == ("❌未找到装备部件 99（这是一个bug，请反馈给开发者）")


@pytest.mark.asyncio
async def test_mount_without_official_image_uses_pending_message() -> None:
    data = FakeData()
    data.values[data.equip] = (
        SimpleNamespace(
            id=1301170,
            name="帝皇驹",
            part_type=SimpleNamespace(id=6),
            suit=None,
            bonus=None,
        ),
    )

    result = await _service(data, MissingImages()).select("equip", 1301170)

    assert result.reply is not None
    assert result.reply.image is None
    assert result.reply.image_error == ""
    assert result.reply.text.endswith("图片：官方图片暂未上线，暂无法展示。")


@pytest.mark.asyncio
async def test_mount_uses_generated_mount_asset_kind() -> None:
    data = FakeData()
    data.values[data.equip] = (
        SimpleNamespace(
            id=1301170,
            name="帝皇驹",
            part_type=SimpleNamespace(id=6),
            suit=None,
            bonus=None,
        ),
    )
    requested: list[tuple[object, str]] = []

    class MountImages(FakeImages):
        async def fetch(
            self,
            kind: object,
            key: str,
            *,
            fallback: bool = True,
        ) -> bytes:
            requested.append((kind, key))
            return await super().fetch(kind, key, fallback=fallback)

    result = await _service(data, MountImages()).select("equip", 1301170)

    assert result.reply is not None
    assert result.reply.image == b"image:1301170"
    assert result.reply.image_error == ""
    assert requested == [("mount", "1301170")]


@pytest.mark.asyncio
@pytest.mark.parametrize("generated_state", ["published", "missing"])
async def test_mount_query_uses_published_generated_png_after_unity_404(
    generated_state: str,
) -> None:
    data = FakeData()
    data.values[data.equip] = (
        SimpleNamespace(
            id=1301170,
            name="帝皇驹",
            part_type=SimpleNamespace(id=6),
            suit=None,
            bonus=None,
        ),
    )
    snapshot = PublishedRenderAssetSnapshot(
        repositories={
            "default": PublishedAssetRepository("example/unity", "a" * 40),
            "mount": PublishedAssetRepository("example/generated", "b" * 40),
        },
        manifest_revision="assets-v3",
        scopes=frozenset({"new_content_standard"}),
    )
    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        is_generated = "/mount/1301170.png" in request.url.path
        published = is_generated and generated_state == "published"
        return httpx.Response(
            200 if published else 404,
            content=b"generated-png" if published else b"",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=lambda: snapshot,
        )
        result = await _service(data, source).select("equip", 1301170)

    assert result.reply is not None
    assert any("/item/cloth/prev/1301170.png" in url for url in requested)
    assert any("/item/cloth/icon/1301170.png" in url for url in requested)
    assert any("/mount/1301170.png" in url for url in requested)
    if generated_state == "published":
        assert result.reply.image == b"generated-png"
        assert "暂未上线" not in result.reply.text
    else:
        assert result.reply.image is None
        assert result.reply.text.endswith("图片：官方图片暂未上线，暂无法展示。")


@pytest.mark.asyncio
async def test_mount_transport_error_is_not_reported_as_missing_image() -> None:
    data = FakeData()
    data.values[data.equip] = (
        SimpleNamespace(
            id=1301170,
            name="帝皇驹",
            part_type=SimpleNamespace(id=6),
            suit=None,
            bonus=None,
        ),
    )
    snapshot = PublishedRenderAssetSnapshot(
        repositories={
            "default": PublishedAssetRepository("example/unity", "a" * 40),
            "mount": PublishedAssetRepository("example/generated", "b" * 40),
        },
        manifest_revision="assets-v3",
        scopes=frozenset({"new_content_standard"}),
    )

    def respond(request: httpx.Request) -> httpx.Response:
        if "/item/cloth/prev/" in request.url.path:
            raise httpx.ConnectError(CONNECTION_FAILED, request=request)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        source = HttpSeerImageSource(
            HttpClients(cache=client, origin=client),
            asset_snapshot_getter=lambda: snapshot,
        )
        result = await _service(data, source).select("equip", 1301170)

    assert result.reply is not None
    assert result.reply.image is None
    assert result.reply.image_error == "图片素材获取失败，暂时无法显示。"
    assert "暂未上线" not in result.reply.text


@pytest.mark.asyncio
async def test_non_mount_missing_image_hides_internal_error() -> None:
    data = FakeData()
    data.values[data.equip] = (
        SimpleNamespace(
            id=400,
            name="普通部件",
            part_type=SimpleNamespace(id=0),
            suit=None,
            bonus=None,
        ),
    )

    result = await _service(data, MissingImages()).select("equip", 400)

    assert result.reply is not None
    assert result.reply.image is None
    assert result.reply.image_error == "图片素材获取失败，暂时无法显示。"
    assert "404" not in result.reply.image_error
