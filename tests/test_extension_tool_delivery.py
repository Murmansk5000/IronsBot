from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from anyio import Path as AsyncPath

from ironsbot.app.extension_tool_install import (
    ToolArchiveGateway,
    install_tools,
    installation_lock,
    probe_tools,
)
from ironsbot.integrations.docker import client as integration
from ironsbot.services.operations.docker_models import DockerImageArchiveRequest

if TYPE_CHECKING:
    from pathlib import Path

_PAYLOAD = b"0123456789"


@pytest.mark.parametrize("limit", [3, 100])
def test_tool_download_is_bounded_and_uses_immutable_image(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, limit: int
) -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.method + " " + request.url.path)
        if request.url.path.startswith("/images/"):
            return httpx.Response(200, json={"Id": "sha256:fixed"})
        if request.url.path == "/containers/create":
            assert b'"Image":"sha256:fixed"' in request.content
            return httpx.Response(201, json={"Id": "stopped-archive"})
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, content=_PAYLOAD)

    monkeypatch.setattr(
        integration.httpx,
        "AsyncHTTPTransport",
        lambda **_: httpx.MockTransport(respond),
    )
    gateway = integration.DockerClient()
    request = DockerImageArchiveRequest("sha256:fixed", "/ironsbot_tools", "socket", 10)
    target = tmp_path / "tools.tar"
    if limit < len(_PAYLOAD):
        with pytest.raises(ValueError, match="budget"):
            asyncio.run(gateway.save_image_archive(request, target, max_bytes=limit))
        assert not target.exists()
    else:
        asyncio.run(gateway.save_image_archive(request, target, max_bytes=limit))
        assert target.read_bytes() == b"0123456789"
    assert calls[-1] == "DELETE /containers/stopped-archive"
    assert not any("/images/create" in call for call in calls)


def test_tool_download_rejects_mutable_tag(tmp_path: Path) -> None:
    request = DockerImageArchiveRequest("private:latest", "/ironsbot_tools", "s", 10)
    with pytest.raises(ValueError, match="immutable"):
        asyncio.run(
            integration.DockerClient().save_image_archive(
                request, tmp_path / "out", max_bytes=100
            )
        )


def test_installation_lock_serializes_concurrent_installers(tmp_path: Path) -> None:
    order: list[str] = []

    async def run() -> None:
        async def job(name: str) -> None:
            async with installation_lock(tmp_path):
                order.append(name)
                await asyncio.sleep(0.02)
                assert order[-1] == name

        await asyncio.gather(job("first"), job("second"))

    asyncio.run(run())
    assert sorted(order) == ["first", "second"]


def test_probe_does_not_inherit_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AI_KEY_FAKE", "never-inherit")
    process = AsyncMock()
    process.wait.return_value = 0
    process.returncode = 0
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    asyncio.run(probe_tools(tmp_path, "ironsbot_private_fake.probe", tmp_path))
    assert "AI_KEY_FAKE" not in create.call_args.kwargs["env"]
    assert "-I" in create.call_args.args


@pytest.mark.parametrize("probe_failed", [False, True])
def test_tool_publication_occurs_only_after_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, probe_failed: bool
) -> None:
    import json

    from ironsbot.app import extension_tool_install as installer
    from ironsbot.app import extension_tools

    code = tmp_path / ".staging-code"
    code.mkdir()
    fingerprint = "a" * 64
    spec = SimpleNamespace(
        fingerprint=fingerprint,
        tool_directory="somua",
        archive_path="/ironsbot_tools",
        probe_module="ironsbot_private_fake.probe",
    )
    monkeypatch.setattr(extension_tools, "read_tool_spec", lambda _: spec)

    def extract(_archive: Path, staging: Path, _spec: object) -> Path:
        runtime = staging / "somua"
        runtime.mkdir(parents=True)
        return runtime

    monkeypatch.setattr(extension_tools, "extract_tool_archive", extract)

    async def probe(_code: Path, _module: str, runtime: Path) -> None:
        assert await AsyncPath(runtime).is_dir()
        assert not (tmp_path / "tools" / fingerprint).exists()
        if probe_failed:
            message = "probe failed"
            raise ValueError(message)

    monkeypatch.setattr(installer, "probe_tools", probe)
    gateway = SimpleNamespace(save_image_archive=AsyncMock())
    request = DockerImageArchiveRequest("sha256:fixed", "/ironsbot_tools", "s", 10)
    if probe_failed:
        with pytest.raises(ValueError, match="probe failed"):
            asyncio.run(
                install_tools(
                    code, tmp_path, cast("ToolArchiveGateway", gateway), request
                )
            )
        assert not (code / ".installed-tools.json").exists()
        assert not (tmp_path / "tools" / fingerprint).exists()
        assert not list((tmp_path / "tools").glob(".staging-*"))
    else:
        asyncio.run(
            install_tools(code, tmp_path, cast("ToolArchiveGateway", gateway), request)
        )
        marker = json.loads((code / ".installed-tools.json").read_text())
        assert marker["tools"]["somua"]["path"] == str(
            (tmp_path / "tools" / fingerprint / "somua").resolve()
        )
    assert gateway.save_image_archive.call_args.args[0].image == "sha256:fixed"
