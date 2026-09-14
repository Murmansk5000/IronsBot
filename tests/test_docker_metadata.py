from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from typing_extensions import Self

from ironsbot.integrations.docker import client as docker_client
from ironsbot.integrations.docker import metadata
from ironsbot.integrations.docker.registry import (
    inspect_registry_image_info,
    registry_image_reference,
    split_docker_image,
)
from ironsbot.services.operations.docker_formatting import (
    format_docker_image_check_reply,
)
from ironsbot.services.operations.docker_models import (
    DockerImageCheckResult,
    DockerImageInfo,
    DockerUpdateRequest,
    WatchtowerUpdateOptions,
)

_METADATA_TIMEOUT_MESSAGE = "metadata request timed out"
_CURRENT_SHA = "a" * 40
_REMOTE_SHA = "b" * 40
_MAIN_SHA = "c" * 40


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    ["", "https://example.org/example/bot", "https://github.com/example"],
)
async def test_commit_summary_without_repository_never_opens_http_client(
    monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    factory = Mock(side_effect=AssertionError("unexpected HTTP client"))
    monkeypatch.setattr(metadata.httpx, "AsyncClient", factory)
    image = DockerImageInfo(
        image_id="sha256:image",
        labels={
            "org.opencontainers.image.source": source,
            "org.opencontainers.image.revision": "abcdef1234567890",
        },
    )
    assert await metadata.resolve_image_commit_summary(image) == ""
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_commit_summary_uses_the_images_own_source_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = "https://api.github.com/repos/example/custom-bot/commits/abcdef1234567890"
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = httpx.Response(
        200,
        request=httpx.Request("GET", url),
        json={"commit": {"message": "custom change\n\nDetails"}},
    )
    monkeypatch.setattr(metadata.httpx, "AsyncClient", Mock(return_value=client))
    image = DockerImageInfo(
        image_id="sha256:image",
        labels={
            "org.opencontainers.image.source": "https://github.com/example/custom-bot.git",
            "org.opencontainers.image.revision": "abcdef1234567890",
        },
    )
    assert (
        await metadata.resolve_image_commit_summary(image)
        == "abcdef123456 custom change"
    )
    client.get.assert_awaited_once()
    assert client.get.await_args.args[0] == url


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["check_update", "start_update"])
async def test_unlabelled_image_never_looks_up_a_deployment_repository(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    image = DockerImageInfo(
        image_id="sha256:same",
        repo_digests=("example/bot@sha256:digest",),
        labels={"org.opencontainers.image.revision": "abcdef1234567890"},
    )
    monkeypatch.setattr(
        docker_client.DockerClient, "socket_exists", AsyncMock(return_value=True)
    )
    for name, value in (
        ("inspect_container_image_id", image.image_id),
        ("inspect_image_info", image),
        ("pull_docker_image", image),
        ("inspect_remote_image_digest", "sha256:digest"),
        ("inspect_remote_image_info", image),
    ):
        monkeypatch.setattr(docker_client, name, AsyncMock(return_value=value))
    get = AsyncMock(side_effect=AssertionError("unexpected metadata HTTP request"))
    monkeypatch.setattr(httpx.AsyncClient, "get", get)
    request = DockerUpdateRequest(
        container_name="example",
        image="example/bot:latest",
        socket_path="/unused/docker.sock",
        timeout_seconds=1,
        watchtower=WatchtowerUpdateOptions(
            image="example/watchtower:latest", docker_api_version="1.44"
        ),
    )
    result = await getattr(docker_client.DockerClient(), operation)(request)
    assert result.ok
    assert result.up_to_date
    assert result.current_image_commit == ""
    get.assert_not_awaited()


def test_commit_lookup_logs_exception_type_when_metadata_request_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, _url: str, **_kwargs: object) -> httpx.Response:
            raise httpx.ReadTimeout(
                _METADATA_TIMEOUT_MESSAGE,
                request=httpx.Request("GET", "https://api.github.com"),
            )

    monkeypatch.setattr(metadata.httpx, "AsyncClient", FakeClient)
    image = DockerImageInfo(
        image_id="sha256:image",
        labels={
            "org.opencontainers.image.source": (
                "https://github.com/Murmansk5000/IronsBot"
            ),
            "org.opencontainers.image.revision": "abcdef1234567890",
        },
    )

    with caplog.at_level(logging.WARNING, logger=metadata.__name__):
        result = asyncio.run(metadata.resolve_image_commit_summary(image))

    assert result == ""
    assert "error_type=ReadTimeout" in caplog.text
    assert f"error=ReadTimeout('{_METADATA_TIMEOUT_MESSAGE}')" in caplog.text


def test_branch_revision_uses_github_main_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, url: str, **_kwargs: object) -> httpx.Response:
            assert url.endswith("/repos/Murmansk5000/IronsBot/commits/main")
            return httpx.Response(
                200,
                json={"sha": "499223c8f23ad9be9e3320725ee70a7b77a14ad5"},
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(metadata.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(
        metadata.resolve_github_branch_revision(("Murmansk5000", "IronsBot"))
    )

    assert result == "499223c8f23ad9be9e3320725ee70a7b77a14ad5"


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/example/bot:preview",
        "ghcr.io/example/bot:preview@sha256:old",
        "ghcr.io/example/bot@sha256:old",
    ],
)
@pytest.mark.asyncio
async def test_check_pins_metadata_and_populates_main_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    image: str,
) -> None:
    current = DockerImageInfo(
        image_id="sha256:current",
        repo_digests=("ghcr.io/example/bot@sha256:observed",),
        labels={
            "org.opencontainers.image.source": "https://github.com/example/previous",
            "org.opencontainers.image.revision": _CURRENT_SHA,
        },
    )
    remote = DockerImageInfo(
        image_id="sha256:remote",
        labels={
            "org.opencontainers.image.source": "https://github.com/example/target.git",
            "org.opencontainers.image.revision": _REMOTE_SHA,
        },
    )
    request = _prepare_check(monkeypatch, current)
    request = replace(request, image=image)
    remote_lookup = AsyncMock(return_value=remote)
    branch_lookup = AsyncMock(return_value=_MAIN_SHA)
    monkeypatch.setattr(docker_client, "inspect_remote_image_info", remote_lookup)
    monkeypatch.setattr(docker_client, "resolve_github_branch_revision", branch_lookup)

    result = await docker_client.DockerClient().check_update(request)

    assert result.ok and result.up_to_date
    assert result.current_image_revision == _CURRENT_SHA
    assert result.remote_image_revision == _REMOTE_SHA
    assert result.github_main_revision == _MAIN_SHA
    assert result.github_main_repository == "example/target"
    assert result.github_main_error == ""
    remote_lookup.assert_awaited_once_with(
        "ghcr.io/example/bot@sha256:observed",
        registry_credentials=None,
    )
    branch_lookup.assert_awaited_once_with(("example", "target"))


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["metadata", "branch", "unlabelled"])
async def test_optional_diagnostics_preserve_digest_result(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    current = DockerImageInfo(
        image_id="sha256:current",
        repo_digests=("ghcr.io/example/bot@sha256:observed",),
        labels=(
            {}
            if failure == "unlabelled"
            else {
                "org.opencontainers.image.source": "https://github.com/example/current",
                "org.opencontainers.image.revision": _CURRENT_SHA,
            }
        ),
    )
    request = _prepare_check(monkeypatch, current)
    metadata_lookup = AsyncMock(return_value=DockerImageInfo("sha256:remote"))
    if failure == "metadata":
        metadata_lookup.side_effect = httpx.ReadTimeout("metadata timeout")
    branch_lookup = AsyncMock(return_value=_MAIN_SHA)
    if failure == "branch":
        branch_lookup.side_effect = httpx.ReadTimeout("sensitive transport detail")
    monkeypatch.setattr(docker_client, "inspect_remote_image_info", metadata_lookup)
    monkeypatch.setattr(docker_client, "resolve_github_branch_revision", branch_lookup)

    result = await docker_client.DockerClient().check_update(request)

    assert result.ok and result.up_to_date
    assert result.remote_digest == "sha256:observed"
    if failure == "unlabelled":
        branch_lookup.assert_not_awaited()
        assert "已跳过" in result.github_main_error
    else:
        branch_lookup.assert_awaited_once_with(("example", "current"))
    if failure == "branch":
        assert result.github_main_error == "ReadTimeout"
        assert result.github_main_revision == ""
    if failure == "metadata":
        assert result.github_main_revision == _MAIN_SHA
        assert result.remote_image_revision == ""


def _prepare_check(
    monkeypatch: pytest.MonkeyPatch,
    current: DockerImageInfo,
) -> DockerUpdateRequest:
    monkeypatch.setattr(
        docker_client.DockerClient, "socket_exists", AsyncMock(return_value=True)
    )
    for name, value in (
        ("inspect_container_image_id", current.image_id),
        ("inspect_image_info", current),
        ("inspect_remote_image_digest", "sha256:observed"),
        ("resolve_image_commit_summary", ""),
    ):
        monkeypatch.setattr(docker_client, name, AsyncMock(return_value=value))
    # A read-only check must never invoke a Docker mutation or real network request.
    monkeypatch.setattr(
        httpx.AsyncClient,
        "get",
        AsyncMock(side_effect=AssertionError("unexpected GET")),
    )
    monkeypatch.setattr(
        httpx.AsyncClient,
        "post",
        AsyncMock(side_effect=AssertionError("unexpected POST")),
    )
    return DockerUpdateRequest(
        container_name="example",
        image="ghcr.io/example/bot:preview",
        socket_path="/unused/docker.sock",
        timeout_seconds=1,
        watchtower=WatchtowerUpdateOptions("example/watchtower:latest", "1.44"),
    )


@pytest.mark.parametrize(
    "image",
    [
        "ghcr.io/example/bot:preview",
        "example/bot:v1",
        "registry.example:5000/bot@sha256:pinned",
    ],
)
@pytest.mark.parametrize("revision", [_MAIN_SHA, _REMOTE_SHA, "", "invalid", "a"])
def test_revision_formatting_does_not_invent_registry_or_commit_order(
    image: str,
    revision: str,
) -> None:
    result = DockerImageCheckResult(
        ok=True,
        up_to_date=True,
        current_image_revision=revision,
        remote_image_revision=revision,
        github_main_repository="example/source",
        github_main_revision=_MAIN_SHA,
    )
    reply = format_docker_image_check_reply(
        container_name="example", image=image, result=result
    )

    assert image in reply
    assert "GitHub 参考仓库：example/source" in reply
    assert "Docker Hub" not in reply
    assert "落后" not in reply
    assert "构建可能" not in reply
    assert "未拉取镜像" in reply
    if revision == _MAIN_SHA:
        assert "目标代码已对齐 GitHub main" in reply
        assert "本机代码已对齐 GitHub main" in reply
    elif revision == _REMOTE_SHA:
        assert "未判断提交先后" in reply
    else:
        assert "无法比较 main" in reply


@pytest.mark.parametrize(
    "image,expected",
    [
        (
            "ghcr.io/example/bot@sha256:abc",
            ("https://ghcr.io", "example/bot", "sha256:abc"),
        ),
        (
            "ghcr.io/example/bot:preview@sha256:abc",
            ("https://ghcr.io", "example/bot", "sha256:abc"),
        ),
        (
            "localhost:5000/bot@sha256:abc",
            ("https://localhost:5000", "bot", "sha256:abc"),
        ),
        ("example/bot:v1", ("https://registry-1.docker.io", "example/bot", "v1")),
    ],
)
def test_registry_reference_preserves_pinned_digest(
    image: str, expected: tuple[str, str, str]
) -> None:
    assert registry_image_reference(image) == expected
    assert split_docker_image(image)[1] == expected[2]


@pytest.mark.asyncio
async def test_registry_reads_exact_digest_not_mutable_tag() -> None:
    paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/manifests/sha256:observed"):
            return httpx.Response(200, json={"config": {"digest": "sha256:config"}})
        assert request.url.path.endswith("/blobs/sha256:config")
        return httpx.Response(
            200,
            json={
                "config": {"Labels": {"org.opencontainers.image.revision": _REMOTE_SHA}}
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        image = await inspect_registry_image_info(
            client, "ghcr.io/example/bot:preview@sha256:observed"
        )
    assert image.image_id == "sha256:config"
    assert image.labels["org.opencontainers.image.revision"] == _REMOTE_SHA
    assert paths == [
        "/v2/example/bot/manifests/sha256:observed",
        "/v2/example/bot/blobs/sha256:config",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{}, {"sha": ""}, {"sha": "not-a-sha"}, {"sha": 12}, []]
)
async def test_branch_revision_rejects_invalid_github_payload(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get.return_value = httpx.Response(
        200,
        request=httpx.Request(
            "GET", "https://api.github.com/repos/example/bot/commits/main"
        ),
        json=payload,
    )
    monkeypatch.setattr(metadata.httpx, "AsyncClient", Mock(return_value=client))
    with pytest.raises(RuntimeError, match="valid commit SHA"):
        await metadata.resolve_github_branch_revision(("example", "bot"))
