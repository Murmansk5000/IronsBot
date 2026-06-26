from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from ironsbot.config.models.runtime import RemoteBuildConfig
from ironsbot.plugins.db_sync.github_actions import (
    WorkflowRunResult,
    trigger_and_wait_workflow,
)

HTTP_ERROR_STATUS = 400


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= HTTP_ERROR_STATUS:
            msg = f"unexpected HTTP status: {self.status_code}"
            raise AssertionError(msg)


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
    ) -> FakeResponse:
        self.posts.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(status_code=204)

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, object] | None = None,
    ) -> FakeResponse:
        _ = (url, params)
        assert headers["Authorization"] == "Bearer token"
        payload = self.get_payloads.pop(0)
        return FakeResponse(payload=payload)


def _config() -> RemoteBuildConfig:
    return RemoteBuildConfig(
        enabled=True,
        repository="Murmansk5000/seerapi",
        workflow_id="build-ironsbot-data-db.yml",
        ref="main",
        timeout_seconds=30,
        poll_interval_seconds=0.01,
    )


def _config_with_inputs() -> RemoteBuildConfig:
    return RemoteBuildConfig(
        enabled=True,
        repository="Murmansk5000/seer-data",
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
        "html_url": "https://github.com/Murmansk5000/seerapi/actions/runs/123",
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
        html_url="https://github.com/Murmansk5000/seerapi/actions/runs/123",
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
