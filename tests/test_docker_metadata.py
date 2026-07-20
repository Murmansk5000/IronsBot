from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import httpx
from typing_extensions import Self

from ironsbot.integrations.docker import metadata
from ironsbot.services.operations.docker_models import DockerImageInfo

if TYPE_CHECKING:
    import pytest

_METADATA_TIMEOUT_MESSAGE = "metadata request timed out"


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
