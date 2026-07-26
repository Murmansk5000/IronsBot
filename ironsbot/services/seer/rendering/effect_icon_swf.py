# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import base64
import struct
import zlib
from collections import defaultdict
from io import BytesIO
from typing import TYPE_CHECKING, NamedTuple

from PIL import Image

from .svg_rasterizer import rasterize_svg

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFINE_BITS_LOSSLESS_2 = 36
DEFINE_SHAPE_4 = 83
EXTENDED_LENGTH_MARKER = 0x3F
EXTENDED_STYLE_COUNT_MARKER = 0xFF
LOSSLESS_ARGB_32_FORMAT = 5
MITER_JOIN_STYLE = 2
LINEAR_GRADIENT = 0x10
RADIAL_GRADIENT = 0x12
FOCAL_RADIAL_GRADIENT = 0x13
REPEATING_BITMAP_FILL = 0x40
CLIPPED_BITMAP_FILL = 0x41
NON_SMOOTHED_REPEATING_BITMAP_FILL = 0x42
NON_SMOOTHED_CLIPPED_BITMAP_FILL = 0x43
MISSING_BITMAP_ID = 0xFFFF
BITMAP_FILL_TYPES = (
    REPEATING_BITMAP_FILL,
    CLIPPED_BITMAP_FILL,
    NON_SMOOTHED_REPEATING_BITMAP_FILL,
    NON_SMOOTHED_CLIPPED_BITMAP_FILL,
)
CLIPPED_BITMAP_FILL_TYPES = (CLIPPED_BITMAP_FILL, NON_SMOOTHED_CLIPPED_BITMAP_FILL)

Color = tuple[int, int, int, int]
Point = tuple[int, int]


class EffectIconImage(NamedTuple):
    data: bytes
    mime_type: str


class _BitmapImage(NamedTuple):
    data: bytes
    width: int
    height: int


class _BitReader:
    def __init__(self, data: bytes, bit: int = 0) -> None:
        self.data = data
        self.bit = bit

    def read(self, count: int) -> int:
        value = 0
        for _ in range(count):
            byte = self.data[self.bit // 8]
            offset = 7 - (self.bit % 8)
            value = (value << 1) | ((byte >> offset) & 1)
            self.bit += 1
        return value

    def read_signed(self, count: int) -> int:
        value = self.read(count)
        if count and value & (1 << (count - 1)):
            value -= 1 << count
        return value

    def align(self) -> None:
        self.bit = (self.bit + 7) // 8 * 8

    @property
    def byte_pos(self) -> int:
        self.align()
        return self.bit // 8

    @byte_pos.setter
    def byte_pos(self, value: int) -> None:
        self.bit = value * 8


class _Matrix(NamedTuple):
    scale_x: float
    rotate_skew_0: float
    rotate_skew_1: float
    scale_y: float
    translate_x: int
    translate_y: int


class _GradientStop(NamedTuple):
    ratio: int
    color: Color


class _FillStyle(NamedTuple):
    fill_type: int
    color: Color | None = None
    matrix: _Matrix | None = None
    bitmap_id: int | None = None
    stops: tuple[_GradientStop, ...] = ()
    spread_mode: int = 0
    interpolation_mode: int = 0
    focal_point: float = 0.0


class _LineStyle(NamedTuple):
    width: int
    fill: _FillStyle
    start_cap: int
    end_cap: int
    join_style: int
    miter_limit: float


class _Edge(NamedTuple):
    start: Point
    control: Point | None
    end: Point

    def reversed(self) -> _Edge:
        return _Edge(self.end, self.control, self.start)


class _ShapeGroup(NamedTuple):
    fill_edges: dict[int, list[_Edge]]
    line_edges: dict[int, list[_Edge]]


class _Shape(NamedTuple):
    bounds: tuple[int, int, int, int]
    fill_styles: tuple[_FillStyle, ...]
    line_styles: tuple[_LineStyle, ...]
    groups: tuple[_ShapeGroup, ...]
    use_fill_winding_rule: bool


class EffectIconSwfError(ValueError):
    pass


def effect_icon_swf_to_image(data: bytes, *, size: int = 96) -> EffectIconImage:
    """Convert an official effect-icon SWF to a browser-renderable image."""
    tags = list(_iter_tags(_swf_body(data)))
    bitmaps: dict[int, _BitmapImage] = {}
    for tag_code, payload in tags:
        if tag_code == DEFINE_BITS_LOSSLESS_2:
            character_id, bitmap = _decode_lossless(payload)
            bitmaps[character_id] = bitmap

    shape_payloads = [
        payload for tag_code, payload in tags if tag_code == DEFINE_SHAPE_4
    ]
    last_error: Exception | None = None
    for payload in shape_payloads:
        image, last_error = _try_render_shape_image(
            payload,
            size=size,
            bitmaps=bitmaps,
        )
        if image is not None:
            return image

    if shape_payloads:
        raise EffectIconSwfError from last_error
    if bitmaps:
        bitmap = next(iter(bitmaps.values()))
        return EffectIconImage(_render_bitmap(bitmap, size=size), "image/png")
    raise EffectIconSwfError


def _try_render_shape_image(
    data: bytes,
    *,
    size: int,
    bitmaps: Mapping[int, _BitmapImage],
) -> tuple[EffectIconImage | None, Exception | None]:
    try:
        svg = _render_shape_svg(data, size=size, bitmaps=bitmaps)
        png = rasterize_svg(svg, size=size)
    except (EffectIconSwfError, ValueError) as error:
        return None, error
    return EffectIconImage(png, "image/png"), None


def _swf_body(data: bytes) -> bytes:
    if data[:3] == b"CWS":
        return zlib.decompress(data[8:])
    if data[:3] == b"FWS":
        return data[8:]
    raise EffectIconSwfError


def _read_rect(data: bytes, pos: int) -> tuple[list[int], int]:
    reader = _BitReader(data, pos * 8)
    bit_count = reader.read(5)
    rect = [reader.read_signed(bit_count) for _ in range(4)]
    return rect, reader.byte_pos


def _read_u8(data: bytes, pos: int) -> tuple[int, int]:
    return data[pos], pos + 1


def _read_u16(data: bytes, pos: int) -> tuple[int, int]:
    return struct.unpack_from("<H", data, pos)[0], pos + 2


def _read_rgba(data: bytes, pos: int) -> tuple[Color, int]:
    return tuple(data[pos : pos + 4]), pos + 4  # type: ignore[return-value]


def _read_count(data: bytes, pos: int) -> tuple[int, int]:
    count, pos = _read_u8(data, pos)
    if count == EXTENDED_STYLE_COUNT_MARKER:
        count, pos = _read_u16(data, pos)
    return count, pos


def _read_matrix(data: bytes, pos: int) -> tuple[_Matrix, int]:
    reader = _BitReader(data, pos * 8)
    scale_x = scale_y = 1.0
    rotate_skew_0 = rotate_skew_1 = 0.0
    if reader.read(1):
        bit_count = reader.read(5)
        scale_x = reader.read_signed(bit_count) / 65536
        scale_y = reader.read_signed(bit_count) / 65536
    if reader.read(1):
        bit_count = reader.read(5)
        rotate_skew_0 = reader.read_signed(bit_count) / 65536
        rotate_skew_1 = reader.read_signed(bit_count) / 65536
    bit_count = reader.read(5)
    translate_x = reader.read_signed(bit_count)
    translate_y = reader.read_signed(bit_count)
    return (
        _Matrix(
            scale_x,
            rotate_skew_0,
            rotate_skew_1,
            scale_y,
            translate_x,
            translate_y,
        ),
        reader.byte_pos,
    )


def _read_fill_style(data: bytes, pos: int) -> tuple[_FillStyle, int]:
    fill_type, pos = _read_u8(data, pos)
    if fill_type == 0:
        color, pos = _read_rgba(data, pos)
        return _FillStyle(fill_type, color=color), pos
    if fill_type in (LINEAR_GRADIENT, RADIAL_GRADIENT, FOCAL_RADIAL_GRADIENT):
        matrix, pos = _read_matrix(data, pos)
        packed, pos = _read_u8(data, pos)
        stops: list[_GradientStop] = []
        for _ in range(packed & 0x0F):
            ratio, pos = _read_u8(data, pos)
            color, pos = _read_rgba(data, pos)
            stops.append(_GradientStop(ratio, color))
        focal_point = 0.0
        if fill_type == FOCAL_RADIAL_GRADIENT:
            focal_raw, pos = _read_u16(data, pos)
            focal_point = struct.unpack("<h", struct.pack("<H", focal_raw))[0] / 256
        return (
            _FillStyle(
                fill_type,
                matrix=matrix,
                stops=tuple(stops),
                spread_mode=packed >> 6,
                interpolation_mode=(packed >> 4) & 0x03,
                focal_point=focal_point,
            ),
            pos,
        )
    if fill_type in BITMAP_FILL_TYPES:
        bitmap_id, pos = _read_u16(data, pos)
        matrix, pos = _read_matrix(data, pos)
        return (
            _FillStyle(
                fill_type,
                matrix=matrix,
                bitmap_id=bitmap_id,
            ),
            pos,
        )
    raise EffectIconSwfError


def _read_line_style(data: bytes, pos: int) -> tuple[_LineStyle, int]:
    width, pos = _read_u16(data, pos)
    reader = _BitReader(data, pos * 8)
    start_cap = reader.read(2)
    join_style = reader.read(2)
    has_fill = bool(reader.read(1))
    reader.read(3)
    reader.read(5)
    reader.read(1)
    end_cap = reader.read(2)
    pos = reader.byte_pos
    miter_limit = 1.0
    if join_style == MITER_JOIN_STYLE:
        miter_raw, pos = _read_u16(data, pos)
        miter_limit = miter_raw / 256
    if has_fill:
        fill, pos = _read_fill_style(data, pos)
    else:
        color, pos = _read_rgba(data, pos)
        fill = _FillStyle(0, color=color)
    return (
        _LineStyle(
            width,
            fill,
            start_cap,
            end_cap,
            join_style,
            miter_limit,
        ),
        pos,
    )


def _read_styles(
    data: bytes,
    pos: int,
) -> tuple[list[_FillStyle], list[_LineStyle], int]:
    fills: list[_FillStyle] = []
    lines: list[_LineStyle] = []
    fill_count, pos = _read_count(data, pos)
    for _ in range(fill_count):
        fill, pos = _read_fill_style(data, pos)
        fills.append(fill)
    line_count, pos = _read_count(data, pos)
    for _ in range(line_count):
        line, pos = _read_line_style(data, pos)
        lines.append(line)
    return fills, lines, pos


def _iter_tags(body: bytes):
    _frame_size, pos = _read_rect(body, 0)
    pos += 4
    while pos + 2 <= len(body):
        code_len = struct.unpack_from("<H", body, pos)[0]
        pos += 2
        tag_code = code_len >> 6
        length = code_len & EXTENDED_LENGTH_MARKER
        if length == EXTENDED_LENGTH_MARKER:
            length = struct.unpack_from("<I", body, pos)[0]
            pos += 4
        yield tag_code, body[pos : pos + length]
        pos += length
        if tag_code == 0:
            break


def _append_segment(
    segment: list[_Edge],
    fill_edges: dict[int, list[_Edge]],
    line_edges: dict[int, list[_Edge]],
    *,
    styles: tuple[int, int, int],
) -> None:
    if not segment:
        return
    fill0, fill1, line = styles
    if fill0:
        fill_edges.setdefault(fill0, []).extend(
            edge.reversed() for edge in reversed(segment)
        )
    if fill1:
        fill_edges.setdefault(fill1, []).extend(segment)
    if line:
        line_edges.setdefault(line, []).extend(segment)


def _parse_shape(data: bytes) -> _Shape:  # noqa: C901, PLR0912, PLR0915
    _shape_id, pos = _read_u16(data, 0)
    raw_bounds, pos = _read_rect(data, pos)
    _edge_bounds, pos = _read_rect(data, pos)
    shape_flags, pos = _read_u8(data, pos)
    fill_styles, line_styles, pos = _read_styles(data, pos)
    reader = _BitReader(data, pos * 8)
    fill_bits = reader.read(4)
    line_bits = reader.read(4)

    all_fills = list(fill_styles)
    all_lines = list(line_styles)
    fill_offset = line_offset = 0
    fill0 = fill1 = line = 0
    x = y = 0
    segment: list[_Edge] = []
    fill_edges: dict[int, list[_Edge]] = defaultdict(list)
    line_edges: dict[int, list[_Edge]] = defaultdict(list)
    groups: list[_ShapeGroup] = []

    def flush_segment() -> None:
        nonlocal segment
        _append_segment(
            segment,
            fill_edges,
            line_edges,
            styles=(fill0, fill1, line),
        )
        segment = []

    def flush_group() -> None:
        nonlocal fill_edges, line_edges
        if fill_edges or line_edges:
            groups.append(_ShapeGroup(dict(fill_edges), dict(line_edges)))
        fill_edges = defaultdict(list)
        line_edges = defaultdict(list)

    while True:
        if reader.read(1):
            straight = bool(reader.read(1))
            bit_count = reader.read(4) + 2
            start = (x, y)
            if straight:
                if reader.read(1):
                    x += reader.read_signed(bit_count)
                    y += reader.read_signed(bit_count)
                elif reader.read(1):
                    y += reader.read_signed(bit_count)
                else:
                    x += reader.read_signed(bit_count)
                segment.append(_Edge(start, None, (x, y)))
            else:
                control = (
                    x + reader.read_signed(bit_count),
                    y + reader.read_signed(bit_count),
                )
                x = control[0] + reader.read_signed(bit_count)
                y = control[1] + reader.read_signed(bit_count)
                segment.append(_Edge(start, control, (x, y)))
            continue

        flags = reader.read(5)
        if flags == 0:
            flush_segment()
            flush_group()
            break

        state_move = bool(flags & 0x01)
        state_fill0 = bool(flags & 0x02)
        state_fill1 = bool(flags & 0x04)
        state_line = bool(flags & 0x08)
        state_new_styles = bool(flags & 0x10)
        if state_fill0 or state_fill1 or state_line:
            flush_segment()

        move_x = move_y = 0
        if state_move:
            bit_count = reader.read(5)
            move_x = reader.read_signed(bit_count)
            move_y = reader.read_signed(bit_count)
        next_fill0 = reader.read(fill_bits) if state_fill0 else fill0
        next_fill1 = reader.read(fill_bits) if state_fill1 else fill1
        next_line = reader.read(line_bits) if state_line else line

        if state_new_styles:
            reader.align()
            pos = reader.byte_pos
            new_fills, new_lines, pos = _read_styles(data, pos)
            fill_offset = len(all_fills)
            line_offset = len(all_lines)
            all_fills.extend(new_fills)
            all_lines.extend(new_lines)
            reader.byte_pos = pos
            fill_bits = reader.read(4)
            line_bits = reader.read(4)

        starts_new_group = (
            state_fill0
            and state_fill1
            and state_line
            and next_fill0 == next_fill1 == next_line == 0
        )
        if starts_new_group:
            flush_group()
            fill0 = fill1 = line = 0
        else:
            if state_fill0:
                fill0 = next_fill0 + fill_offset if next_fill0 else 0
            if state_fill1:
                fill1 = next_fill1 + fill_offset if next_fill1 else 0
            if state_line:
                line = next_line + line_offset if next_line else 0
        if state_move:
            x, y = move_x, move_y

    return _Shape(
        (raw_bounds[0], raw_bounds[1], raw_bounds[2], raw_bounds[3]),
        tuple(all_fills),
        tuple(all_lines),
        tuple(groups),
        bool(shape_flags & 0x04),
    )


def _ordered_contours(edges: list[_Edge]) -> list[list[_Edge]]:
    by_start: dict[Point, list[int]] = defaultdict(list)
    for index, edge in enumerate(edges):
        by_start[edge.start].append(index)
    remaining = set(range(len(edges)))
    contours: list[list[_Edge]] = []
    while remaining:
        index = min(remaining)
        contour: list[_Edge] = []
        while index in remaining:
            remaining.remove(index)
            edge = edges[index]
            contour.append(edge)
            candidates = by_start.get(edge.end, [])
            next_index = next((item for item in candidates if item in remaining), -1)
            if next_index < 0:
                break
            index = next_index
        contours.append(contour)
    return contours


def _number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _point(point: Point) -> str:
    return f"{_number(point[0] / 20)} {_number(point[1] / 20)}"


def _path_data(edges: list[_Edge], *, close: bool) -> str:
    commands: list[str] = []
    for contour in _ordered_contours(edges):
        if not contour:
            continue
        commands.append(f"M {_point(contour[0].start)}")
        for edge in contour:
            if edge.control is None:
                commands.append(f"L {_point(edge.end)}")
            else:
                commands.append(f"Q {_point(edge.control)} {_point(edge.end)}")
        if close:
            commands.append("Z")
    return " ".join(commands)


def _color(color: Color) -> str:
    return f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"


def _opacity(color: Color) -> str:
    return _number(color[3] / 255)


def _matrix_value(matrix: _Matrix) -> str:
    values = (
        matrix.scale_x,
        matrix.rotate_skew_0,
        matrix.rotate_skew_1,
        matrix.scale_y,
        matrix.translate_x / 20,
        matrix.translate_y / 20,
    )
    return "matrix(" + " ".join(_number(value) for value in values) + ")"


def _bitmap_matrix_value(matrix: _Matrix) -> str:
    values = (
        matrix.scale_x / 20,
        matrix.rotate_skew_0 / 20,
        matrix.rotate_skew_1 / 20,
        matrix.scale_y / 20,
        matrix.translate_x / 20,
        matrix.translate_y / 20,
    )
    return "matrix(" + " ".join(_number(value) for value in values) + ")"


def _fill_attributes(
    style: _FillStyle,
    defs: list[str],
) -> tuple[str, str | None]:
    if style.color is not None:
        return _color(style.color), _opacity(style.color)
    if style.matrix is None or not style.stops:
        raise EffectIconSwfError
    gradient_id = f"gradient-{len(defs) + 1}"
    spread = {0: "pad", 1: "reflect", 2: "repeat"}.get(style.spread_mode, "pad")
    interpolation = (
        ' color-interpolation="linearRGB"'
        if style.interpolation_mode == 1
        else ""
    )
    transform = _matrix_value(style.matrix)
    stops = "".join(
        (
            f'<stop offset="{_number(stop.ratio / 255)}" '
            f'stop-color="{_color(stop.color)}" '
            f'stop-opacity="{_opacity(stop.color)}"/>'
        )
        for stop in style.stops
    )
    if style.fill_type == LINEAR_GRADIENT:
        gradient = (
            f'<linearGradient id="{gradient_id}" gradientUnits="userSpaceOnUse" '
            f'x1="-819.2" y1="0" x2="819.2" y2="0" '
            f'gradientTransform="{transform}" spreadMethod="{spread}"'
            f"{interpolation}>{stops}</linearGradient>"
        )
    else:
        gradient = (
            f'<radialGradient id="{gradient_id}" gradientUnits="userSpaceOnUse" '
            f'cx="0" cy="0" r="819.2" '
            f'fx="{_number(819.2 * style.focal_point)}" fy="0" '
            f'gradientTransform="{transform}" spreadMethod="{spread}"'
            f"{interpolation}>{stops}</radialGradient>"
        )
    defs.append(gradient)
    return f"url(#{gradient_id})", None


def _render_shape_svg(
    data: bytes,
    *,
    size: int,
    bitmaps: Mapping[int, _BitmapImage] | None = None,
) -> bytes:
    return _render_shape_svg_from_shape(
        _parse_shape(data),
        size=size,
        bitmaps=bitmaps,
    )


def _render_shape_svg_from_shape(
    shape: _Shape,
    *,
    size: int,
    bitmaps: Mapping[int, _BitmapImage] | None = None,
) -> bytes:
    min_x, max_x, min_y, max_y = shape.bounds
    view_box = " ".join(
        _number(value)
        for value in (
            min_x / 20,
            min_y / 20,
            (max_x - min_x) / 20,
            (max_y - min_y) / 20,
        )
    )
    defs: list[str] = []
    body: list[str] = []
    bitmap_map = bitmaps or {}
    fill_rule = "nonzero" if shape.use_fill_winding_rule else "evenodd"
    for group in shape.groups:
        for style_id in sorted(group.fill_edges):
            if not 0 < style_id <= len(shape.fill_styles):
                continue
            path = _path_data(group.fill_edges[style_id], close=True)
            style = shape.fill_styles[style_id - 1]
            if style.fill_type in BITMAP_FILL_TYPES:
                definition, element = _bitmap_fill_markup(
                    style,
                    path=path,
                    fill_rule=fill_rule,
                    bitmaps=bitmap_map,
                    definition_index=len(defs) + 1,
                )
                if definition is not None:
                    defs.append(definition)
                if element is not None:
                    body.append(element)
                continue
            fill, opacity = _fill_attributes(style, defs)
            opacity_attr = f' fill-opacity="{opacity}"' if opacity != "1" else ""
            body.append(
                f'<path d="{path}" fill="{fill}"{opacity_attr} '
                f'fill-rule="{fill_rule}"/>'
            )
        for style_id in sorted(group.line_edges):
            if not 0 < style_id <= len(shape.line_styles):
                continue
            style = shape.line_styles[style_id - 1]
            path = _path_data(group.line_edges[style_id], close=False)
            stroke, opacity = _fill_attributes(style.fill, defs)
            opacity_attr = f' stroke-opacity="{opacity}"' if opacity != "1" else ""
            line_cap = {0: "round", 1: "butt", 2: "square"}.get(
                style.start_cap,
                "round",
            )
            line_join = {0: "round", 1: "bevel", 2: "miter"}.get(
                style.join_style,
                "round",
            )
            body.append(
                f'<path d="{path}" fill="none" stroke="{stroke}"{opacity_attr} '
                f'stroke-width="{_number(style.width / 20)}" '
                f'stroke-linecap="{line_cap}" stroke-linejoin="{line_join}" '
                f'stroke-miterlimit="{_number(style.miter_limit)}"/>'
            )
    defs_markup = f"<defs>{''.join(defs)}</defs>" if defs else ""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="{view_box}" preserveAspectRatio="xMidYMid meet">'
        f"{defs_markup}{''.join(body)}</svg>"
    )
    return svg.encode()


def _bitmap_fill_markup(
    style: _FillStyle,
    *,
    path: str,
    fill_rule: str,
    bitmaps: Mapping[int, _BitmapImage],
    definition_index: int,
) -> tuple[str | None, str | None]:
    if style.bitmap_id is None or style.matrix is None:
        raise EffectIconSwfError
    bitmap = bitmaps.get(style.bitmap_id)
    if bitmap is None:
        if style.bitmap_id == MISSING_BITMAP_ID:
            return None, None
        raise EffectIconSwfError

    image_uri = "data:image/png;base64," + base64.b64encode(bitmap.data).decode(
        "ascii"
    )
    transform = _bitmap_matrix_value(style.matrix)
    rendering = (
        "optimizeSpeed"
        if style.fill_type
        in {NON_SMOOTHED_REPEATING_BITMAP_FILL, NON_SMOOTHED_CLIPPED_BITMAP_FILL}
        else "optimizeQuality"
    )
    if style.fill_type in CLIPPED_BITMAP_FILL_TYPES:
        clip_id = f"bitmap-clip-{definition_index}"
        definition = (
            f'<clipPath id="{clip_id}"><path d="{path}" '
            f'fill-rule="{fill_rule}"/></clipPath>'
        )
        element = (
            f'<image href="{image_uri}" width="{bitmap.width}" '
            f'height="{bitmap.height}" transform="{transform}" '
            f'clip-path="url(#{clip_id})" image-rendering="{rendering}"/>'
        )
        return definition, element

    pattern_id = f"bitmap-pattern-{definition_index}"
    definition = (
        f'<pattern id="{pattern_id}" patternUnits="userSpaceOnUse" '
        f'width="{bitmap.width}" height="{bitmap.height}" '
        f'patternTransform="{transform}"><image href="{image_uri}" '
        f'width="{bitmap.width}" height="{bitmap.height}" '
        f'image-rendering="{rendering}"/></pattern>'
    )
    element = (
        f'<path d="{path}" fill="url(#{pattern_id})" fill-rule="{fill_rule}"/>'
    )
    return definition, element


def _decode_lossless(data: bytes) -> tuple[int, _BitmapImage]:
    character_id, pos = _read_u16(data, 0)
    bitmap_format, pos = _read_u8(data, pos)
    width, pos = _read_u16(data, pos)
    height, pos = _read_u16(data, pos)
    if bitmap_format != LOSSLESS_ARGB_32_FORMAT:
        raise EffectIconSwfError

    raw = zlib.decompress(data[pos:])
    pixels = bytearray()
    for index in range(0, len(raw), 4):
        alpha, red, green, blue = raw[index : index + 4]
        pixels.extend((red, green, blue, alpha))
    source = Image.frombytes("RGBA", (width, height), bytes(pixels))
    output = BytesIO()
    source.save(output, format="PNG")
    return character_id, _BitmapImage(output.getvalue(), width, height)


def _render_bitmap(bitmap: _BitmapImage, *, size: int) -> bytes:
    source = Image.open(BytesIO(bitmap.data)).convert("RGBA")
    source.thumbnail((size, size), Image.Resampling.LANCZOS)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    image.alpha_composite(
        source,
        ((size - source.width) // 2, (size - source.height) // 2),
    )
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
