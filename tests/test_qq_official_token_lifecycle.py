from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.integrations.qq_official.token_lifecycle import QQOfficialTokenObserver

if TYPE_CHECKING:
    from qqbot_agent_sdk.api_client import QQApiClient


class _FakeApi:
    def __init__(self) -> None:
        self.token = "first-sensitive-token"

    async def ensure_token(self) -> str:
        return self.token

    def ensure_token_sync(self) -> str:
        return self.token


@pytest.mark.asyncio
async def test_token_observer_reports_acquisition_and_rotation_without_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="ironsbot.integrations.qq_official.token_lifecycle",
    )
    api = _FakeApi()
    observer = QQOfficialTokenObserver("example-account")

    await observer.ensure(cast("QQApiClient", api))
    await observer.ensure(cast("QQApiClient", api))
    api.token = "second-sensitive-token"
    observer.ensure_sync(cast("QQApiClient", api))

    assert caplog.text.count("access token acquired") == 1
    assert caplog.text.count("access token refreshed") == 1
    assert "account=example-account" in caplog.text
    assert "first-sensitive-token" not in caplog.text
    assert "second-sensitive-token" not in caplog.text
