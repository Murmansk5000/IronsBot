from pathlib import Path

from ironsbot.config.loader import tomllib


def test_version_file_project_and_lock_describe_same_release() -> None:
    root = Path(__file__).resolve().parents[1]
    declared = (
        (root / "__version__").read_text(encoding="utf-8").strip().removeprefix("v")
    )
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    package = next(item for item in lock["package"] if item["name"] == "ironsbot")
    assert declared == project["project"]["version"] == package["version"]
