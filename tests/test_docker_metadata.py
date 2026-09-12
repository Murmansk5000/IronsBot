from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from typing_extensions import Self

from ironsbot.integrations.docker import client as docker_client
from ironsbot.integrations.docker import metadata
from ironsbot.services.operations.docker_models import (
    DockerImageInfo,
    DockerUpdateRequest,
    WatchtowerUpdateOptions,
)

_METADATA_TIMEOUT_MESSAGE = "metadata request timed out"


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
