# SPDX-License-Identifier: MIT
"""Runtime metadata for the repository that built this IronsBot instance."""

from __future__ import annotations

import os
from configparser import ConfigParser
from configparser import Error as ConfigParserError
from pathlib import Path

DEFAULT_PROJECT_URL = "https://github.com/Murmansk5000/IronsBot"
PROJECT_URL_ENV = "IRONSBOT_PROJECT_URL"


def _checkout_project_url() -> str:
    config_path = Path.cwd() / ".git" / "config"
    if not config_path.is_file():
        return ""
    parser = ConfigParser(strict=False)
    try:
        parser.read(config_path, encoding="utf-8")
        origin = parser.get('remote "origin"', "url", fallback="").strip()
    except (OSError, ConfigParserError, ValueError):
        return ""
    if origin.startswith("git@github.com:"):
        origin = f"https://github.com/{origin.removeprefix('git@github.com:')}"
    elif origin.startswith("ssh://git@github.com/"):
        origin = f"https://github.com/{origin.removeprefix('ssh://git@github.com/')}"
    return origin.removesuffix(".git").rstrip("/")


def current_project_url() -> str:
    """Return the repository URL injected by the current build environment."""
    if configured := os.environ.get(PROJECT_URL_ENV, "").strip():
        return configured.rstrip("/")
    if repository := os.environ.get("GITHUB_REPOSITORY", "").strip().strip("/"):
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        return f"{server}/{repository}"
    if checkout_url := _checkout_project_url():
        return checkout_url
    return DEFAULT_PROJECT_URL
