# SPDX-License-Identifier: MIT
# ruff: noqa: T201
"""Repository health checks for local development and CI-like smoke tests."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".ps1",
    ".sh",
    ".svg",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

BINARY_SUFFIXES = {
    ".db",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".sqlite",
    ".webp",
    ".zip",
}

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "data",
    "logs",
    "node_modules",
    "render_cache",
}

MOJIBAKE_MARKERS = {
    "\ufffd",
    "\u951b",
    "\u9286",
    "\u9225",
    "\u9477",
    "\u9369",
    "\u9428",
    "\u6d60",
    "\u7ed4",
    "\u93bb",
    "\u95c2",
}
MOJIBAKE_MARKER_THRESHOLD = 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Run IronsBot repository checks.")
    parser.add_argument(
        "--static",
        action="store_true",
        help="Only parse config files and scan text encodings.",
    )
    args = parser.parse_args()

    checks = [
        ("pyproject", check_pyproject),
        ("yaml", check_yaml_files),
        ("xml", check_xml_files),
        ("utf8", check_text_encoding),
    ]

    if not args.static:
        checks.extend(
            [
                ("ruff", run_ruff),
                ("pytest", run_pytest),
                ("compileall", run_compileall),
                ("git-diff-check", run_git_diff_check),
            ],
        )

    failed = False
    for name, check in checks:
        print(f"==> {name}", flush=True)
        code = check()
        if code != 0:
            failed = True
            print(f"!! {name} failed with exit code {code}", flush=True)

    return 1 if failed else 0


def check_pyproject() -> int:
    with (ROOT / "pyproject.toml").open("rb") as file:
        tomllib.load(file)
    return 0


def check_yaml_files() -> int:
    paths = [
        ROOT / ".pre-commit-config.yaml",
        ROOT / "docker-compose.yml",
        *(ROOT / ".github" / "workflows").glob("*.yml"),
        *(ROOT / ".github" / "workflows").glob("*.yaml"),
    ]
    for path in sorted({p for p in paths if p.exists()}):
        with path.open("r", encoding="utf-8") as file:
            yaml.safe_load(file)
    return 0


def check_xml_files() -> int:
    paths = [
        ROOT / "ca_profile.xml",
        *(ROOT / "templates").glob("*.xml"),
    ]
    for path in sorted(p for p in paths if p.exists()):
        ET.parse(path)
    return 0


def check_text_encoding() -> int:
    failures: list[str] = []
    for path in iter_text_files(ROOT):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{relative(path)}: not valid UTF-8 ({exc})")
            continue

        marker_count = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
        if marker_count >= MOJIBAKE_MARKER_THRESHOLD:
            failures.append(
                f"{relative(path)}: possible mojibake markers={marker_count}",
            )

    for failure in failures:
        print(failure)
    return 1 if failures else 0


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if should_skip(path):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {
            ".editorconfig",
            ".gitattributes",
            ".gitignore",
            "Dockerfile",
            "LICENSE",
        }:
            yield path


def should_skip(path: Path) -> bool:
    relative_parts = path.relative_to(ROOT).parts
    return any(part in SKIP_DIRS for part in relative_parts)


def run_ruff() -> int:
    return run_command(("uv", "run", "ruff", "check", "ironsbot", "tests", "scripts"))


def run_pytest() -> int:
    return run_command(
        (
            "uv",
            "run",
            "pytest",
            "tests/test_app_config_loader.py",
            "tests/test_bilibili_monitor_state.py",
            "tests/test_bilibili_monitor_runtime.py",
            "tests/test_messaging_unsubscribe_service.py",
            "tests/test_feature_service.py",
            "tests/test_feature_visibility.py",
            "tests/test_team_resource_config.py",
            "tests/test_plugin_import_hygiene.py",
        ),
    )


def run_compileall() -> int:
    return run_command(("uv", "run", "python", "-m", "compileall", "-q", "ironsbot"))


def run_git_diff_check() -> int:
    return run_command(("git", "-c", "core.autocrlf=false", "diff", "--check"))


def run_command(command: Sequence[str]) -> int:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(command, cwd=ROOT, env=env, check=False)
    return result.returncode


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
