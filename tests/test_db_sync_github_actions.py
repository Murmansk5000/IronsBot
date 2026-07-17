from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from ironsbot.config.models.runtime import RemoteBuildConfig
from ironsbot.integrations.db_sync.github_actions import (
    GitHubActionsClientError,
    WorkflowRunResult,
    trigger_and_wait_workflow,
)


def _response(
    *,
    status_code: int = 200,
    payload: dict[str, Any] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://api.github.test/"),
    )


class FakeGitHubClient:
    def __init__(self, get_payloads: list[dict[str, Any]]) -> None:
        self.posts: list[dict[str, object]] = []
        self.get_payloads = get_payloads

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx.Response:
        self.posts.append({"url": url, "headers": headers, "json": json})
        return _response(status_code=204)

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        _ = (url, params)
        assert headers["Authorization"] == "Bearer token"
        payload = self.get_payloads.pop(0)
        return _response(payload=payload)


class FlakyDispatchGitHubClient(FakeGitHubClient):
    def __init__(self, get_payloads: list[dict[str, Any]]) -> None:
        super().__init__(get_payloads)
        self.failed_once = False

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx.Response:
        if not self.failed_once:
            self.failed_once = True
            raise httpx.ConnectTimeout("connect timeout")  # noqa: TRY003
        return await super().post(url, headers=headers, json=json)


class DeniedDispatchGitHubClient(FakeGitHubClient):
    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx.Response:
        self.posts.append({"url": url, "headers": headers, "json": json})
        return _response(
            status_code=403,
            payload={
                "message": (
                    "Resource not accessible by personal access token"
                )
            },
        )


def _config() -> RemoteBuildConfig:
    return RemoteBuildConfig(
        enabled=True,
        repository="Murmansk-Seer/seerapi",
        workflow_id="build-ironsbot-data-db.yml",
        ref="main",
        timeout_seconds=30,
        poll_interval_seconds=0.01,
    )


def _config_with_inputs() -> RemoteBuildConfig:
    return RemoteBuildConfig(
        enabled=True,
        repository="Murmansk-Seer/api-data",
        workflow_id="main.yml",
        ref="main",
        timeout_seconds=30,
        poll_interval_seconds=0.01,
        inputs={"debug_enabled": False},
    )


def _run_payload(*, status: str, conclusion: str | None) -> dict[str, Any]:
    return {
        "id": 123,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "html_url": "https://github.com/Murmansk-Seer/seerapi/actions/runs/123",
        "status": status,
        "conclusion": conclusion,
    }


def test_trigger_and_wait_workflow_returns_success() -> None:
    client = FakeGitHubClient(
        [
            {"workflow_runs": [_run_payload(status="queued", conclusion=None)]},
            _run_payload(status="completed", conclusion="success"),
        ]
    )

    result = asyncio.run(
        trigger_and_wait_workflow(_config(), token="token", client=client)
    )

    assert result == WorkflowRunResult(
        ok=True,
        status="completed",
        conclusion="success",
        html_url="https://github.com/Murmansk-Seer/seerapi/actions/runs/123",
        message="GitHub workflow completed successfully",
    )
    assert client.posts[0]["json"] == {"ref": "main"}


def test_trigger_and_wait_workflow_returns_failure() -> None:
    client = FakeGitHubClient(
        [
            {"workflow_runs": [_run_payload(status="queued", conclusion=None)]},
            _run_payload(status="completed", conclusion="failure"),
        ]
    )

    result = asyncio.run(
        trigger_and_wait_workflow(_config(), token="token", client=client)
    )

    assert not result.ok
    assert result.conclusion == "failure"
    assert "failure" in result.message


def test_trigger_and_wait_workflow_dispatches_inputs() -> None:
    client = FakeGitHubClient(
        [
            {"workflow_runs": [_run_payload(status="queued", conclusion=None)]},
            _run_payload(status="completed", conclusion="success"),
        ]
    )

    result = asyncio.run(
        trigger_and_wait_workflow(
            _config_with_inputs(),
            token="token",
            client=client,
        )
    )

    assert result.ok
    assert client.posts[0]["json"] == {
        "ref": "main",
        "inputs": {"debug_enabled": False},
    }


def test_trigger_and_wait_workflow_retries_transient_dispatch_timeout() -> None:
    client = FlakyDispatchGitHubClient(
        [
            {"workflow_runs": [_run_payload(status="queued", conclusion=None)]},
            _run_payload(status="completed", conclusion="success"),
        ]
    )

    result = asyncio.run(
        trigger_and_wait_workflow(_config(), token="token", client=client)
    )

    assert result.ok
    assert client.failed_once
    assert len(client.posts) == 1


def test_trigger_and_wait_workflow_reports_dispatch_error_detail() -> None:
    client = DeniedDispatchGitHubClient([])

    with pytest.raises(
        GitHubActionsClientError,
        match="Resource not accessible by personal access token",
    ):
        asyncio.run(
            trigger_and_wait_workflow(_config(), token="token", client=client)
        )
