from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "ironsbot"
MAX_PRODUCTION_PYTHON_LINES = 800


def _production_python_files() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


def test_production_python_files_stay_below_size_limit() -> None:
    oversized = [
        f"{path.relative_to(ROOT).as_posix()} has {line_count} lines"
        for path in _production_python_files()
        if (line_count := len(path.read_text(encoding="utf-8-sig").splitlines()))
        > MAX_PRODUCTION_PYTHON_LINES
    ]

    assert oversized == []
