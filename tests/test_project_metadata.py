from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from ironsbot.integrations.htmlkit import render_html_template
from ironsbot.integrations.project_metadata import current_project_url


def test_current_project_url_uses_build_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IRONSBOT_PROJECT_URL", " https://example.test/fork/bot/ ")

    assert current_project_url() == "https://example.test/fork/bot"


def test_current_project_url_is_empty_without_build_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IRONSBOT_PROJECT_URL", raising=False)

    assert current_project_url() == ""


@pytest.mark.asyncio
async def test_html_renderer_injects_project_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def template_to_pic(*args: Any, **_kwargs: Any) -> bytes:
        captured["context"] = args[2]
        return b"image"

    monkeypatch.setenv("IRONSBOT_PROJECT_URL", "https://example.test/fork/bot")
    monkeypatch.setitem(
        sys.modules,
        "nonebot_plugin_htmlkit",
        SimpleNamespace(template_to_pic=template_to_pic),
    )

    result = await render_html_template("templates", "page.j2", {"value": 1})

    assert result == b"image"
    assert captured["context"] == {
        "value": 1,
        "project_url": "https://example.test/fork/bot",
    }
