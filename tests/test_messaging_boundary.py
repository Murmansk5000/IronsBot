from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PLUGIN_HELPER_IMPORT = "from ironsbot.plugins.messaging import"


def _python_files_under(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        files.extend(root.rglob("*.py"))
    return files


def test_feature_code_uses_shared_messaging_helpers() -> None:
    scanned_files = [
        path
        for path in _python_files_under(ROOT / "ironsbot" / "plugins")
        if "ironsbot/plugins/messaging" not in path.as_posix()
    ]
    scanned_files.extend(_python_files_under(ROOT / "ironsbot" / "services"))

    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in scanned_files
        if FORBIDDEN_PLUGIN_HELPER_IMPORT in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
