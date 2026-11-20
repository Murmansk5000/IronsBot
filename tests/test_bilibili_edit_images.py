from io import BytesIO

from PIL import Image, ImageDraw

from ironsbot.integrations.bilibili_image_diff import compare_images
from ironsbot.services.bilibili.edit_diff import media_changes, text_changes

SOURCE_HEIGHT = 2000


def picture(
    *, changed: bool = False, size: tuple[int, int] = (300, 2000), fmt: str = "PNG"
) -> bytes:
    image = Image.new("RGB", size, "white")
    if changed:
        ImageDraw.Draw(image).rectangle((80, 700, 150, 780), fill="red")
    stream = BytesIO()
    image.save(stream, format=fmt)
    return stream.getvalue()


def test_numeric_text_change_keeps_entire_values_and_original_text() -> None:
    fragments = text_changes("奖励50个<&>", "奖励55个<&>")
    assert [(f.text, f.kind) for f in fragments if f.kind != "equal"] == [
        ("50", "delete"),
        ("55", "insert"),
    ]
    assert "".join(f.text for f in fragments if f.kind != "insert") == "奖励50个<&>"
    assert "".join(f.text for f in fragments if f.kind != "delete") == "奖励55个<&>"


def test_local_change_uses_equal_bounded_crops() -> None:
    result = compare_images(picture(), picture(changed=True))
    assert not result.identical
    assert "局部" in result.note
    assert len(result.panels) == 1
    before, after = result.panels[0]
    assert before is not None and after is not None
    with Image.open(BytesIO(before)) as left, Image.open(BytesIO(after)) as right:
        assert left.size == right.size
        assert left.height < SOURCE_HEIGHT


def test_lossless_encoding_change_does_not_claim_visible_edit() -> None:
    result = compare_images(picture(), picture(fmt="BMP"))
    assert result.identical


def test_changed_dimensions_and_missing_sides_are_honest() -> None:
    result = compare_images(picture(), picture(size=(400, 2000)))
    assert "尺寸" in result.note
    missing = compare_images(None, picture())
    assert missing.panels[0][0] is None
    assert "缺少" in missing.note


def test_compression_noise_is_not_called_a_local_semantic_change() -> None:
    source = Image.new("RGB", (300, 2000), "#b4d8ec")
    a, b = BytesIO(), BytesIO()
    source.save(a, format="JPEG", quality=40)
    source.save(b, format="PNG")
    result = compare_images(a.getvalue(), b.getvalue())
    assert result.identical or "不可靠" in result.note


def test_reordering_and_addition_preserve_media_identity() -> None:
    before = ["https://i0.hdslb.com/a.png", "https://i0.hdslb.com/b.png"]
    after = ["http://i2.hdslb.com/b.png?token=x", "https://i0.hdslb.com/a.png"]
    assert all(change.moved for change in media_changes(before, after))
    deleted = media_changes(before, before[:1])
    assert deleted[0].after_index is None
    added = media_changes(before[:1], before)
    assert added[0].before_index is None


def test_transparency_change_is_a_visible_edit() -> None:
    opaque, transparent = BytesIO(), BytesIO()
    Image.new("RGBA", (100, 100), (0, 0, 0, 255)).save(opaque, format="PNG")
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(transparent, format="PNG")
    assert not compare_images(opaque.getvalue(), transparent.getvalue()).identical
