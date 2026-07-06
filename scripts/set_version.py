# SPDX-License-Identifier: MIT
# ruff: noqa: T201
"""Set the project version and sync the root ``__version__`` file."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "__version__"

# 宽松校验，具体格式仍由 `uv version` 判定
_VERSION_RE = re.compile(r"^[0-9A-Za-z.+-]+$")


def normalize_pep_version(raw: str) -> str:
    s = raw.strip()
    if s[:1].lower() == "v":
        s = s[1:]
    return s


def validate_local(version: str) -> None:
    if not version:
        sys.exit("版本不能为空")
    if not _VERSION_RE.fullmatch(version):
        sys.exit(f"无效的版本字符串: {version!r}")


def read_project_version_line(pyproject: Path) -> str | None:
    text = pyproject.read_text(encoding="utf-8")
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = False
            continue
        if in_project and stripped.startswith("version"):
            m = re.match(r'version\s*=\s*"([^"]+)"', stripped)
            if m:
                return m.group(1)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  uv run python scripts/set_version.py 1.2.3\n"
            "  uv run python scripts/set_version.py 1.2.3 --git-tag\n"
            "\n"
            "--git-tag 应在已提交 pyproject.toml 与 __version__ 之后使用，"
            "使标签指向包含该版本的提交。"
        ),
    )
    parser.add_argument(
        "version",
        help='PEP 440 版本号，例如 1.2.3 或 "1.2.3a1"（也可写 v1.2.3）',
    )
    parser.add_argument(
        "--git-tag",
        action="store_true",
        help="在当前 HEAD 创建轻量标签 v<version>",
    )
    args = parser.parse_args()

    pep_ver = normalize_pep_version(args.version)
    validate_local(pep_ver)

    subprocess.run(
        ["uv", "version", pep_ver],
        cwd=ROOT,
        check=True,
    )

    tag_label = f"v{pep_ver}"
    VERSION_FILE.write_text(f"{tag_label}\n", encoding="utf-8")

    after = read_project_version_line(ROOT / "pyproject.toml")
    if after != pep_ver:
        sys.exit(
            f"内部错误: pyproject 中 version 为 {after!r}，与期望值 {pep_ver!r} 不一致"
        )

    print(f"已设置版本为 {pep_ver}，并已写入 {VERSION_FILE.relative_to(ROOT)}")

    if args.git_tag:
        subprocess.run(
            ["git", "tag", tag_label],
            cwd=ROOT,
            check=True,
        )
        print(f"已创建 git 标签 {tag_label}")


if __name__ == "__main__":
    main()
