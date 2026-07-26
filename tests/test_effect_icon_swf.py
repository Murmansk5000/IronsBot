# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import struct
from io import BytesIO
from typing import TYPE_CHECKING, cast

from PIL import Image

from ironsbot.services.seer.rendering import effect_icon_swf
from ironsbot.services.seer.rendering.svg_rasterizer import rasterize_svg

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    import pytest


def _png_bytes(color: tuple[int, int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (2, 2), color).save(output, format="PNG")
    return output.getvalue()


def test_line_style_miter_keeps_following_color_aligned() -> None:
    color = (18, 63, 146, 255)
    data = b"".join(
        (
            b"\x00",  # no fill styles
            b"\x01",  # one line style
            struct.pack("<H", 120),
            b"\xa0\x02",  # miter join, no fill
            struct.pack("<H", 3 * 256),
            bytes(color),
        )
    )

    fills, lines, pos = effect_icon_swf._read_styles(data, 0)

    assert fills == []
    assert lines == [
        effect_icon_swf._LineStyle(
            120,
            effect_icon_swf._FillStyle(0, color=color),
            2,
            2,
            2,
            3.0,
        )
    ]
    assert pos == len(data)


def test_fill_only_shape_has_no_synthetic_stroke() -> None:
    shape = effect_icon_swf._Shape(
        bounds=(0, 20, 0, 20),
        fill_styles=(effect_icon_swf._FillStyle(0, color=(58, 37, 32, 255)),),
        line_styles=(),
        groups=(
            effect_icon_swf._ShapeGroup(
                fill_edges={
                    1: [
                        effect_icon_swf._Edge((0, 0), None, (20, 0)),
                        effect_icon_swf._Edge((20, 0), None, (10, 20)),
                        effect_icon_swf._Edge((10, 20), None, (0, 0)),
                    ]
                },
                line_edges={},
            ),
        ),
        use_fill_winding_rule=False,
    )

    svg = effect_icon_swf._render_shape_svg_from_shape(shape, size=32).decode()

    assert 'fill="#3a2520"' in svg
    assert "stroke=" not in svg
    assert "#f24267" not in svg


def test_shape_edges_keep_distinct_left_and_right_fills() -> None:
    first = effect_icon_swf._Edge((0, 0), None, (20, 0))
    second = effect_icon_swf._Edge((20, 0), (30, 10), (20, 20))
    fill_edges: dict[int, list[effect_icon_swf._Edge]] = {}
    line_edges: dict[int, list[effect_icon_swf._Edge]] = {}

    effect_icon_swf._append_segment(
        [first, second],
        fill_edges,
        line_edges,
        styles=(1, 2, 3),
    )

    assert fill_edges[1] == [second.reversed(), first.reversed()]
    assert fill_edges[2] == [first, second]
    assert line_edges[3] == [first, second]


def test_svg_preserves_gradient_stops_and_transform() -> None:
    gradient = effect_icon_swf._FillStyle(
        effect_icon_swf.LINEAR_GRADIENT,
        matrix=effect_icon_swf._Matrix(1, 0, 0, 1, 20, 40),
        stops=(
            effect_icon_swf._GradientStop(0, (46, 125, 205, 255)),
            effect_icon_swf._GradientStop(255, (133, 238, 241, 255)),
        ),
    )
    shape = effect_icon_swf._Shape(
        bounds=(0, 20, 0, 20),
        fill_styles=(gradient,),
        line_styles=(),
        groups=(
            effect_icon_swf._ShapeGroup(
                fill_edges={
                    1: [
                        effect_icon_swf._Edge((0, 0), None, (20, 0)),
                        effect_icon_swf._Edge((20, 0), None, (20, 20)),
                        effect_icon_swf._Edge((20, 20), None, (0, 0)),
                    ]
                },
                line_edges={},
            ),
        ),
        use_fill_winding_rule=False,
    )

    svg = effect_icon_swf._render_shape_svg_from_shape(shape, size=32).decode()

    assert 'gradientTransform="matrix(1 0 0 1 1 2)"' in svg
    assert 'stop-color="#2e7dcd"' in svg
    assert 'stop-color="#85eef1"' in svg


def test_converter_prefers_shape_over_standalone_embedded_bitmap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bitmap = effect_icon_swf._BitmapImage(
        _png_bytes((255, 0, 0, 255)),
        2,
        2,
    )

    def fake_swf_body(data: bytes) -> bytes:
        return data

    def fake_iter_tags(_data: bytes) -> Iterator[tuple[int, bytes]]:
        yield effect_icon_swf.DEFINE_BITS_LOSSLESS_2, b"bitmap"
        yield effect_icon_swf.DEFINE_SHAPE_4, b"shape"

    def fake_decode_lossless(
        _data: bytes,
    ) -> tuple[int, effect_icon_swf._BitmapImage]:
        return 7, bitmap

    def fake_render_shape_svg(
        data: bytes,
        *,
        size: int,
        bitmaps: Mapping[int, effect_icon_swf._BitmapImage] | None = None,
    ) -> bytes:
        assert data == b"shape"
        assert size > 0
        assert bitmaps == {7: bitmap}
        return (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">'
            b'<rect width="1" height="1" fill="#336699"/></svg>'
        )

    monkeypatch.setattr(effect_icon_swf, "_swf_body", fake_swf_body)
    monkeypatch.setattr(effect_icon_swf, "_iter_tags", fake_iter_tags)
    monkeypatch.setattr(effect_icon_swf, "_decode_lossless", fake_decode_lossless)
    monkeypatch.setattr(effect_icon_swf, "_render_shape_svg", fake_render_shape_svg)

    result = effect_icon_swf.effect_icon_swf_to_image(b"swf", size=32)

    assert result.mime_type == "image/png"
    with Image.open(BytesIO(result.data)) as image:
        assert image.size == (32, 32)
        pixel = cast("tuple[int, int, int, int]", image.getpixel((16, 16)))
        assert pixel[:3] == (51, 102, 153)


def test_clipped_bitmap_fill_is_embedded_and_rasterized() -> None:
    bitmap = effect_icon_swf._BitmapImage(
        _png_bytes((214, 99, 255, 255)),
        2,
        2,
    )
    shape = effect_icon_swf._Shape(
        bounds=(0, 40, 0, 40),
        fill_styles=(
            effect_icon_swf._FillStyle(
                effect_icon_swf.CLIPPED_BITMAP_FILL,
                matrix=effect_icon_swf._Matrix(20, 0, 0, 20, 0, 0),
                bitmap_id=7,
            ),
        ),
        line_styles=(),
        groups=(
            effect_icon_swf._ShapeGroup(
                fill_edges={
                    1: [
                        effect_icon_swf._Edge((0, 0), None, (40, 0)),
                        effect_icon_swf._Edge((40, 0), None, (40, 40)),
                        effect_icon_swf._Edge((40, 40), None, (0, 40)),
                        effect_icon_swf._Edge((0, 40), None, (0, 0)),
                    ]
                },
                line_edges={},
            ),
        ),
        use_fill_winding_rule=False,
    )

    svg = effect_icon_swf._render_shape_svg_from_shape(
        shape,
        size=32,
        bitmaps={7: bitmap},
    ).decode()

    assert "data:image/png;base64," in svg
    assert 'clip-path="url(#bitmap-clip-1)"' in svg
    assert 'transform="matrix(1 0 0 1 0 0)"' in svg

    png = rasterize_svg(svg.encode(), size=32)
    with Image.open(BytesIO(png)) as image:
        pixel = cast("tuple[int, int, int, int]", image.getpixel((16, 16)))
        assert pixel[:3] == (214, 99, 255)
