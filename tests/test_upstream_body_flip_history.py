from io import BytesIO

import pytest
from PIL import Image, UnidentifiedImageError

from ironsbot.integrations.seer_data.pet_info_renderer import _flip_pet_body


def test_body_is_pixel_mirrored_once_without_mutating_source() -> None:
    with Image.new("RGBA", (2, 1)) as source:
        source.putpixel((0, 0), (200, 10, 20, 45))
        source.putpixel((1, 0), (30, 40, 210, 160))
        buffer = BytesIO()
        source.save(buffer, format="PNG")
    original = buffer.getvalue()
    flipped = _flip_pet_body(original)
    with Image.open(BytesIO(flipped)) as result:
        assert result.mode == "RGBA"
        assert result.getpixel((0, 0)) == (30, 40, 210, 160)
        assert result.getpixel((1, 0)) == (200, 10, 20, 45)
    with Image.open(BytesIO(original)) as unchanged:
        assert unchanged.getpixel((0, 0)) == (200, 10, 20, 45)


def test_invalid_body_remains_a_decode_error_at_the_pure_boundary() -> None:
    with pytest.raises(UnidentifiedImageError):
        _flip_pet_body(b"invalid")
