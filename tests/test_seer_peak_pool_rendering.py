from __future__ import annotations

import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from ironsbot.core import time
from ironsbot.services.seer.peak import (
    PeakPetSnapshot,
    PeakPoolRenderSnapshot,
    PeakPoolSnapshot,
    PeakPoolTransitionSnapshot,
)
from ironsbot.services.seer.rendering.peak_pool import render_peak_pool

EXPECTED_RENDER_COUNT = 2
RGBA_CHANNEL_COUNT = 4
OPAQUE_ALPHA = 255


def _test_png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (2, 2), (80, 160, 240, 192)).save(output, format="PNG")
    return output.getvalue()


class _Cache:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def get(self, namespace: str, key: str) -> bytes | None:
        return self.values.get((namespace, key))

    def put(self, namespace: str, key: str, value: bytes) -> None:
        self.values[(namespace, key)] = value


class _Images:
    async def fetch(
        self,
        kind: str,
        key: str,
        *,
        fallback: bool = True,
    ) -> bytes:
        del kind, key, fallback
        return _test_png()


def _data_uri_pixel(value: str) -> tuple[int, int, int, int]:
    data = base64.b64decode(value.partition(",")[2])
    with Image.open(BytesIO(data)) as image:
        pixel = image.convert("RGBA").getpixel((0, 0))
    if not isinstance(pixel, tuple) or len(pixel) != RGBA_CHANNEL_COUNT:
        raise AssertionError(pixel)
    return (int(pixel[0]), int(pixel[1]), int(pixel[2]), int(pixel[3]))


def _data_uri_image(value: str) -> Image.Image:
    data = base64.b64decode(value.partition(",")[2])
    with Image.open(BytesIO(data)) as image:
        return image.convert("RGBA")


def _filled_slots(pool: dict[str, Any]) -> list[dict[str, Any]]:
    return [slot for slot in pool["slots"] if slot is not None]


def _pet_slot(
    pool: dict[str, Any],
    *,
    pet_id: int,
    historical: bool,
    columns: int,
) -> tuple[int, int, dict[str, Any]]:
    matches = [
        (index, slot)
        for index, slot in enumerate(pool["slots"])
        if slot is not None
        and slot["id"] == pet_id
        and slot["historical"] is historical
    ]
    if len(matches) != 1:
        raise AssertionError(matches)
    index, pet = matches[0]
    row, column = divmod(index, columns)
    return row, column, pet


def _pool(*pets: PeakPetSnapshot, count: int = 0) -> PeakPoolSnapshot:
    return PeakPoolSnapshot(
        id=count + 1,
        count=count,
        start_time=datetime(2026, 8, 1, tzinfo=time.TZ_CN),
        end_time=datetime(2026, 8, 31, tzinfo=time.TZ_CN),
        pets=tuple(pets),
    )


@pytest.mark.asyncio
async def test_standard_pool_renders_current_and_historical_positions() -> None:
    moved = PeakPetSnapshot(1, "迁移精灵", 1001, 4)
    removed = PeakPetSnapshot(2, "移出精灵", 1002, 5)
    snapshot = PeakPoolRenderSnapshot(
        pools=(_pool(moved, count=0),),
        transitions=(
            PeakPoolTransitionSnapshot(moved, 2, 0),
            PeakPoolTransitionSnapshot(removed, 3, None),
        ),
        change_state="changed",
        content_version="20260814:2026-08-14",
        expert=False,
    )
    captured: dict[str, Any] = {}

    async def render_html(*_args: object, **kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"pool-image"

    result = await render_peak_pool(
        _Cache(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        snapshot,
        "竞技池 / 2026-08-01 ~ 2026-08-31",
    )

    assert result == b"pool-image"
    pools = {pool["label"]: pool for pool in captured["pools"]}
    assert tuple(pools) == ("限0", "限2", "限3", "不限")
    assert [
        (pet["id"], pet["historical"])
        for pet in _filled_slots(pools["限0"])
    ] == [
        (1, False)
    ]
    assert [
        (pet["id"], pet["historical"])
        for pet in _filled_slots(pools["限2"])
    ] == [
        (1, True)
    ]
    assert [
        (pet["id"], pet["historical"])
        for pet in _filled_slots(pools["限3"])
    ] == [
        (2, True)
    ]
    assert [
        (pet["id"], pet["historical"])
        for pet in _filled_slots(pools["不限"])
    ] == [
        (2, False)
    ]
    arrows = {
        arrow.transition_id: arrow for arrow in captured["transition_arrows"]
    }
    assert arrows[0].start_y > arrows[0].line_end_y
    assert arrows[1].start_y < arrows[1].line_end_y
    current_pixel = _data_uri_pixel(
        _filled_slots(pools["限0"])[0]["head_img"]
    )
    historical_pixel = _data_uri_pixel(
        _filled_slots(pools["限2"])[0]["head_img"]
    )
    assert current_pixel == (80, 160, 240, 192)
    assert historical_pixel == (64, 74, 84, 192)


@pytest.mark.asyncio
async def test_expert_pool_uses_only_disabled_and_unlimited_sections() -> None:
    entered = PeakPetSnapshot(1, "新禁用", 1001, 4)
    snapshot = PeakPoolRenderSnapshot(
        pools=(_pool(entered),),
        transitions=(PeakPoolTransitionSnapshot(entered, None, 0),),
        change_state="changed",
        content_version="20260814:2026-08-14",
        expert=True,
    )
    captured: dict[str, Any] = {}

    async def render_html(*_args: object, **kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"expert-image"

    await render_peak_pool(
        _Cache(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        snapshot,
        "专家禁用池 / 2026-08-01 ~ 2026-08-31",
    )

    pools = {pool["label"]: pool for pool in captured["pools"]}
    assert tuple(pools) == ("禁用", "不限")
    columns = captured["grid_columns"]
    base_columns = captured["base_columns"]
    disabled = _filled_slots(pools["禁用"])[0]
    unlimited = _filled_slots(pools["不限"])[0]
    assert disabled["historical"] is False
    assert unlimited["historical"] is True
    disabled_slot = _pet_slot(
        pools["禁用"], pet_id=entered.id, historical=False, columns=columns
    )
    unlimited_slot = _pet_slot(
        pools["不限"], pet_id=entered.id, historical=True, columns=columns
    )
    assert disabled_slot[1] == unlimited_slot[1] == base_columns
    assert (
        disabled["head_img"]
        != unlimited["head_img"]
    )


@pytest.mark.asyncio
async def test_adjacent_transition_uses_matching_nearest_edge_slots() -> None:
    moved = PeakPetSnapshot(100, "迁移精灵", 1100, 4)
    limit_two = tuple(
        PeakPetSnapshot(index, f"限二{index}", 2000 + index, 5)
        for index in range(1, 13)
    )
    snapshot = PeakPoolRenderSnapshot(
        pools=(
            _pool(*limit_two, count=2),
            _pool(moved, count=3),
        ),
        transitions=(PeakPoolTransitionSnapshot(moved, 2, 3),),
        change_state="changed",
        content_version="adjacent",
        expert=False,
    )
    captured: dict[str, Any] = {}

    async def render_html(*_args: object, **kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"adjacent"

    await render_peak_pool(
        _Cache(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        snapshot,
        "竞技池",
    )

    columns = captured["grid_columns"]
    base_columns = captured["base_columns"]
    pools = {pool["label"]: pool for pool in captured["pools"]}
    old_row, old_column, _ = _pet_slot(
        pools["限2"], pet_id=moved.id, historical=True, columns=columns
    )
    new_row, new_column, _ = _pet_slot(
        pools["限3"], pet_id=moved.id, historical=False, columns=columns
    )
    assert old_column == new_column == base_columns
    arrow = captured["transition_arrows"][0]
    assert arrow.transition_id == 0
    assert arrow.start_y < arrow.line_end_y
    overlay = _data_uri_image(captured["transition_overlay"])
    assert overlay.getchannel("A").getbbox() is not None
    overlay_pixel = overlay.getpixel((arrow.x, arrow.start_y))
    assert isinstance(overlay_pixel, tuple)
    assert len(overlay_pixel) == RGBA_CHANNEL_COUNT
    assert int(overlay_pixel[3]) == OPAQUE_ALPHA
    assert old_row == pools["限2"]["rows"] - 1
    assert new_row == 0
    assert all(
        index % columns < base_columns
        for index, slot in enumerate(pools["限2"]["slots"])
        if slot is not None and slot["id"] != moved.id
    )


@pytest.mark.asyncio
async def test_nonadjacent_transition_uses_empty_bypass_column() -> None:
    moved = PeakPetSnapshot(100, "跨级精灵", 1100, 4)
    middle = tuple(
        PeakPetSnapshot(index, f"限二{index}", 2000 + index, 5)
        for index in range(1, 5)
    )
    snapshot = PeakPoolRenderSnapshot(
        pools=(
            _pool(*middle, count=2),
            _pool(moved, count=3),
        ),
        transitions=(PeakPoolTransitionSnapshot(moved, 0, 3),),
        change_state="changed",
        content_version="bypass",
        expert=False,
    )
    captured: dict[str, Any] = {}

    async def render_html(*_args: object, **kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"bypass"

    await render_peak_pool(
        _Cache(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        snapshot,
        "竞技池",
    )

    columns = captured["grid_columns"]
    bypass_column = captured["base_columns"]
    pools = {pool["label"]: pool for pool in captured["pools"]}
    old_row, old_column, _ = _pet_slot(
        pools["限0"], pet_id=moved.id, historical=True, columns=columns
    )
    new_row, new_column, _ = _pet_slot(
        pools["限3"], pet_id=moved.id, historical=False, columns=columns
    )
    assert columns == bypass_column + 1
    assert old_column == new_column == bypass_column
    assert old_row == pools["限0"]["rows"] - 1
    assert new_row == 0
    assert all(
        pool["slots"][row * columns + bypass_column] is None
        for pool in (pools["限2"],)
        for row in range(pool["rows"])
    )


@pytest.mark.asyncio
async def test_many_adjacent_transitions_expand_columns_without_stacking() -> None:
    moved = tuple(
        PeakPetSnapshot(index, f"迁移{index}", 3000 + index, 4)
        for index in range(1, 13)
    )
    snapshot = PeakPoolRenderSnapshot(
        pools=(_pool(*moved, count=2),),
        transitions=tuple(
            PeakPoolTransitionSnapshot(pet, 0, 2) for pet in moved
        ),
        change_state="changed",
        content_version="many-adjacent",
        expert=False,
    )
    captured: dict[str, Any] = {}

    async def render_html(*_args: object, **kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"many"

    await render_peak_pool(
        _Cache(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        snapshot,
        "竞技池",
    )

    columns = captured["grid_columns"]
    base_columns = captured["base_columns"]
    pools = {pool["label"]: pool for pool in captured["pools"]}
    assert base_columns == 1
    assert columns == base_columns + len(moved)
    assert pools["限0"]["rows"] == pools["限2"]["rows"] == 1
    transition_columns: set[int] = set()
    for pet in moved:
        old = _pet_slot(
            pools["限0"], pet_id=pet.id, historical=True, columns=columns
        )
        new = _pet_slot(
            pools["限2"], pet_id=pet.id, historical=False, columns=columns
        )
        assert old[:2] == new[:2]
        assert old[1] >= base_columns
        transition_columns.add(old[1])
    assert transition_columns == set(range(base_columns, columns))


@pytest.mark.asyncio
async def test_touching_transition_ranges_use_separate_lanes() -> None:
    from_above = PeakPetSnapshot(1, "上方迁入", 4001, 4)
    from_below = PeakPetSnapshot(2, "下方迁入", 4002, 5)
    snapshot = PeakPoolRenderSnapshot(
        pools=(_pool(from_above, from_below, count=2),),
        transitions=(
            PeakPoolTransitionSnapshot(from_above, 0, 2),
            PeakPoolTransitionSnapshot(from_below, 3, 2),
        ),
        change_state="changed",
        content_version="opposite-edges",
        expert=False,
    )
    captured: dict[str, Any] = {}

    async def render_html(*_args: object, **kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"opposite"

    await render_peak_pool(
        _Cache(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        snapshot,
        "竞技池",
    )

    columns = captured["grid_columns"]
    base_columns = captured["base_columns"]
    pools = {pool["label"]: pool for pool in captured["pools"]}
    top = _pet_slot(
        pools["限2"],
        pet_id=from_above.id,
        historical=False,
        columns=columns,
    )
    bottom = _pet_slot(
        pools["限2"],
        pet_id=from_below.id,
        historical=False,
        columns=columns,
    )
    assert top[1] != bottom[1]
    assert top[1] >= base_columns
    assert bottom[1] >= base_columns
    assert top[0] == 0
    assert bottom[0] == pools["限2"]["rows"] - 1
    assert top[:2] != bottom[:2]


@pytest.mark.asyncio
async def test_disjoint_transition_ranges_reuse_right_lane() -> None:
    upper = PeakPetSnapshot(1, "上半区迁移", 5001, 4)
    lower = PeakPetSnapshot(2, "下半区迁移", 5002, 5)
    snapshot = PeakPoolRenderSnapshot(
        pools=(_pool(upper, count=2),),
        transitions=(
            PeakPoolTransitionSnapshot(upper, 0, 2),
            PeakPoolTransitionSnapshot(lower, 3, None),
        ),
        change_state="changed",
        content_version="disjoint-lanes",
        expert=False,
    )
    captured: dict[str, Any] = {}

    async def render_html(*_args: object, **kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        return b"disjoint"

    await render_peak_pool(
        _Cache(),  # type: ignore[arg-type]
        _Images(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        snapshot,
        "竞技池",
    )

    columns = captured["grid_columns"]
    base_columns = captured["base_columns"]
    pools = {pool["label"]: pool for pool in captured["pools"]}
    slots = (
        _pet_slot(
            pools["限0"],
            pet_id=upper.id,
            historical=True,
            columns=columns,
        ),
        _pet_slot(
            pools["限2"],
            pet_id=upper.id,
            historical=False,
            columns=columns,
        ),
        _pet_slot(
            pools["限3"],
            pet_id=lower.id,
            historical=True,
            columns=columns,
        ),
        _pet_slot(
            pools["不限"],
            pet_id=lower.id,
            historical=False,
            columns=columns,
        ),
    )
    assert columns == base_columns + 1
    assert {slot[1] for slot in slots} == {base_columns}


@pytest.mark.asyncio
async def test_ordinary_grid_chooses_columns_and_rows_from_content() -> None:
    for pet_count, expected_columns, expected_rows in ((3, 3, 1), (12, 10, 2)):
        pets = tuple(
            PeakPetSnapshot(index, f"普通{index}", 6000 + index, 4)
            for index in range(1, pet_count + 1)
        )
        captured: dict[str, Any] = {}

        async def render_html(
            *_args: object,
            _captured: dict[str, Any] = captured,
            **kwargs: Any,
        ) -> bytes:
            _captured.update(kwargs["templates"])
            return b"ordinary"

        await render_peak_pool(
            _Cache(),  # type: ignore[arg-type]
            _Images(),  # type: ignore[arg-type]
            render_html,  # type: ignore[arg-type]
            PeakPoolRenderSnapshot(
                pools=(_pool(*pets),),
                transitions=(),
                change_state="unchanged",
                content_version=f"ordinary-{pet_count}",
                expert=False,
            ),
            "竞技池",
        )

        pools = {pool["label"]: pool for pool in captured["pools"]}
        assert captured["base_columns"] == expected_columns
        assert captured["grid_columns"] == expected_columns
        assert captured["transition_overlay"] == ""
        assert pools["限0"]["rows"] == expected_rows


@pytest.mark.asyncio
async def test_pool_cache_key_changes_with_weekly_content_version() -> None:
    pet = PeakPetSnapshot(1, "测试精灵", 1001, 4)
    cache = _Cache()
    renders = 0

    async def render_html(*_args: object, **_kwargs: Any) -> bytes:
        nonlocal renders
        renders += 1
        return f"render-{renders}".encode()

    for version in ("20260814:first", "20260814:second"):
        await render_peak_pool(
            cache,  # type: ignore[arg-type]
            _Images(),  # type: ignore[arg-type]
            render_html,  # type: ignore[arg-type]
            PeakPoolRenderSnapshot(
                pools=(_pool(pet),),
                transitions=(),
                change_state="unchanged",
                content_version=version,
                expert=False,
            ),
            "竞技池",
        )

    assert renders == EXPECTED_RENDER_COUNT


def test_pool_template_uses_preprocessed_heads_and_svg_arrows() -> None:
    template = (
        Path(__file__).parents[1]
        / "ironsbot/services/seer/rendering/templates/peak_pool/template.html.j2"
    ).read_text(encoding="utf-8")

    assert "filter:" not in template
    assert "opacity:" not in template
    assert "<strong>灰暗</strong>：上周所在位置" in template
    assert "pet-entry placeholder" in template
    assert "width: {{ grid_width }}px" in template
    assert 'src="{{ transition_overlay }}"' in template
    assert "<svg" not in template
    assert "<script>" not in template
    assert "→" not in template
