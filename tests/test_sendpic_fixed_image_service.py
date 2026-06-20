from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ironsbot"
    / "plugins"
    / "sendpic"
    / "fixed_image_service.py"
)
_SPEC = spec_from_file_location(
    "sendpic_fixed_image_service_for_test",
    _SERVICE_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
_SERVICE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SERVICE)
build_fixed_image_segment = _SERVICE.build_fixed_image_segment


def test_build_fixed_image_segment_returns_none_for_missing_file(
    tmp_path: Path,
) -> None:
    assert build_fixed_image_segment(tmp_path, "missing.png") is None


def test_build_fixed_image_segment_encodes_file_as_base64_image(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"abc")

    segment = build_fixed_image_segment(tmp_path, "sample.png")

    assert segment is not None
    assert segment.type == "image"
    assert segment.data["file"] == "base64://YWJj"
