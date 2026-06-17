import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SELECTED_INDEX = 2
RANDOM_INDEX = 3
MAX_INDEX = 5
OUT_OF_RANGE_INDEX = 6

_SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ironsbot"
    / "plugins"
    / "sendpic"
    / "image_selection_service.py"
)
_SPEC = spec_from_file_location(
    "sendpic_image_selection_service_for_test",
    _SERVICE_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
_SERVICE = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SERVICE
_SPEC.loader.exec_module(_SERVICE)
ImageIndexOutOfRangeError = _SERVICE.ImageIndexOutOfRangeError
InvalidImageArgumentError = _SERVICE.InvalidImageArgumentError
build_image_file_path = _SERVICE.build_image_file_path
select_image = _SERVICE.select_image


def test_select_image_uses_numeric_argument() -> None:
    selection = select_image(str(SELECTED_INDEX), MAX_INDEX)

    assert selection.index == SELECTED_INDEX
    assert not selection.is_random
    assert selection.random_text == "自选"


def test_select_image_uses_random_factory_for_empty_argument() -> None:
    selection = select_image(
        "",
        MAX_INDEX,
        random_index_factory=lambda: RANDOM_INDEX,
    )

    assert selection.index == RANDOM_INDEX
    assert selection.is_random
    assert selection.random_text == "随机"


def test_select_image_rejects_non_numeric_argument() -> None:
    with pytest.raises(InvalidImageArgumentError):
        select_image("abc", 5)


def test_select_image_rejects_out_of_range_index() -> None:
    with pytest.raises(ImageIndexOutOfRangeError) as exc_info:
        select_image(str(OUT_OF_RANGE_INDEX), MAX_INDEX)

    assert exc_info.value.max_index == MAX_INDEX
    assert str(exc_info.value) == "编号必须在1到5之间！"


def test_build_image_file_path_formats_index() -> None:
    assert build_image_file_path("pets", "{index}.png", 3) == "pets/3.png"
