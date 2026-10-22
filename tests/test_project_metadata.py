from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import pytest

from ironsbot.integrations.htmlkit import render_html_template
from ironsbot.integrations.project_metadata import current_project_url

if TYPE_CHECKING:
    from pathlib import Path


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
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    caller = threading.get_ident()
    from jinja2 import Environment

    get_template = Environment.get_template

    def load_template(self: Environment, name: str) -> Any:
        assert threading.get_ident() != caller
        return get_template(self, name)

    async def renderer(html: str, **_kwargs: Any) -> bytes:
        captured["html"] = html
        return b"image"

    monkeypatch.setenv("IRONSBOT_PROJECT_URL", "https://example.test/fork/bot")
    monkeypatch.setattr("ironsbot.integrations.htmlkit.render_html", renderer)
    monkeypatch.setattr(Environment, "get_template", load_template)
    (tmp_path / "page.j2").write_text("{{ value }}|{{ project_url }}", encoding="utf-8")

    result = await render_html_template(tmp_path, "page.j2", {"value": 1})

    assert result == b"image"
    assert captured["html"] == "1|https://example.test/fork/bot"
