# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from resvg_py import svg_to_bytes


def rasterize_svg(svg: bytes, *, size: int) -> bytes:
    return svg_to_bytes(
        svg_string=svg.decode("utf-8"),
        width=size,
        height=size,
        skip_system_fonts=True,
    )
