from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from ironsbot.integrations.htmlkit import render_html_template
from ironsbot.project_metadata import DEFAULT_PROJECT_URL, current_project_url

if TYPE_CHECKING:
    from pathlib import Path


def test_current_project_url_prefers_build_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IRONSBOT_PROJECT_URL", "https://github.com/fork/IronsBot/")
    monkeypatch.setenv("GITHUB_REPOSITORY", "ignored/repository")

    assert current_project_url() == "https://github.com/fork/IronsBot"


def test_current_project_url_uses_github_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IRONSBOT_PROJECT_URL", raising=False)
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.example.test/")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/IronsBot")

    assert current_project_url() == "https://github.example.test/owner/IronsBot"


def test_current_project_url_has_source_checkout_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IRONSBOT_PROJECT_URL", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.chdir(tmp_path)

    assert current_project_url() == DEFAULT_PROJECT_URL


def test_current_project_url_reads_checkout_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IRONSBOT_PROJECT_URL", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = git@github.com:fork-owner/IronsBot.git\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert current_project_url() == "https://github.com/fork-owner/IronsBot"


@pytest.mark.asyncio
async def test_html_renderer_injects_current_project_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def template_to_pic(*args: Any, **_kwargs: Any) -> bytes:
        captured["context"] = args[2]
        return b"image"

    monkeypatch.setenv("IRONSBOT_PROJECT_URL", "https://github.com/fork/IronsBot")
    monkeypatch.setitem(
        sys.modules,
        "nonebot_plugin_htmlkit",
        SimpleNamespace(template_to_pic=template_to_pic),
    )

    result = await render_html_template("templates", "page.j2", {"value": 1})

    assert result == b"image"
    assert captured["context"] == {
        "value": 1,
        "project_url": "https://github.com/fork/IronsBot",
    }
