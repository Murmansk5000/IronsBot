# SPDX-License-Identifier: MIT
"""Conservative Pillow comparisons; source images are never overwritten."""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageChops, ImageFilter, ImageOps

from ironsbot.services.bilibili.edit_diff import ImageComparison

MAX_PIXELS = 40_000_000
MAX_PANELS = 4
CONTEXT = 150
NOISE_THRESHOLD = 24


def _image(content: bytes) -> tuple[Image.Image, bool]:
    with Image.open(BytesIO(content)) as source:
        if source.width * source.height > MAX_PIXELS:
            message = "comparison source exceeds pixel limit"
            raise ValueError(message)
        animated = getattr(source, "n_frames", 1) > 1
        rgba = ImageOps.exif_transpose(source).convert("RGBA")
        return Image.alpha_composite(
            Image.new("RGBA", rgba.size, "white"), rgba
        ).convert("RGB"), animated


def _png(image: Image.Image) -> bytes:
    target = BytesIO()
    image.save(target, format="PNG")
    return target.getvalue()


def compare_images(before: bytes | None, after: bytes | None) -> ImageComparison:
    old, old_animated = _image(before) if before else (None, False)
    new, new_animated = _image(after) if after else (None, False)
    if old is None or new is None:
        return ImageComparison(
            ((_png(old) if old else None, _png(new) if new else None),),
            "缺少一侧图片，无法定位局部变化。",
        )
    complete = ((_png(old), _png(new)),)
    if old_animated or new_animated:
        return ImageComparison(complete, "动图仅展示首帧，不判断其他帧的修改。")
    if old.size != new.size:
        return ImageComparison(complete, "图片尺寸变化，展示整图对照。")
    if ImageChops.difference(old, new).getbbox() is None:
        return ImageComparison(
            complete, "解码像素一致，仅文件编码或元信息变化。", identical=True
        )
    channels = ImageChops.difference(
        old.filter(ImageFilter.GaussianBlur(1)),
        new.filter(ImageFilter.GaussianBlur(1)),
    ).split()
    delta = ImageChops.lighter(
        ImageChops.lighter(channels[0], channels[1]), channels[2]
    )
    mask = delta.point(
        [255 if value > NOISE_THRESHOLD else 0 for value in range(256)]
    ).filter(ImageFilter.MinFilter(3))
    rows = mask.getprojection()[1]
    bands: list[list[int]] = []
    for y, changed in enumerate(rows):
        if not changed:
            continue
        if bands and y - bands[-1][1] <= CONTEXT * 2:
            bands[-1][1] = y
        else:
            bands.append([y, y])
    crops = [
        (0, max(0, lo - CONTEXT), old.width, min(old.height, hi + CONTEXT + 1))
        for lo, hi in bands
    ]
    if (
        not crops
        or len(crops) > MAX_PANELS
        or sum(c[3] - c[1] for c in crops) > old.height / 2
    ):
        return ImageComparison(
            complete,
            "文件发生变化，但压缩、排版或大范围变化使局部定位不可靠；展示整图。",
        )
    return ImageComparison(
        tuple((_png(old.crop(box)), _png(new.crop(box))) for box in crops),
        "展示检测到的局部变化；已容忍部分压缩噪声，不推测修改含义。",
    )
