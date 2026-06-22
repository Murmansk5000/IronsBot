# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol

import httpx

if TYPE_CHECKING:
    from ironsbot.config.models.runtime import RemoteBuildStepConfig

GITHUB_API_BASE_URL = "https://api.github.com"
RUN_MATCH_WINDOW_SECONDS = 30
HTTP_NO_CONTENT = 204


class GitHubActionsClientError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class AsyncGitHubClient(Protocol):
    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> httpx.Response: ...

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, object] | None = None,
    ) -> httpx.Response: ...


@dataclass(frozen=True, slots=True)
class WorkflowRunResult:
    ok: bool
    status: str
    conclusion: str | None
    html_url: str
    message: str


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _parse_github_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _workflow_url(repository: str, workflow_id: str) -> str:
    return f"{GITHUB_API_BASE_URL}/repos/{repository}/actions/workflows/{workflow_id}"


def _run_url(repository: str, run_id: int) -> str:
    return f"{GITHUB_API_BASE_URL}/repos/{repository}/actions/runs/{run_id}"


def _match_workflow_run(
    runs: list[dict[str, Any]],
    *,
    ref: str,
    started_at: datetime,
) -> dict[str, Any] | None:
    earliest = started_at - timedelta(seconds=RUN_MATCH_WINDOW_SECONDS)
    for run in runs:
        if run.get("event") != "workflow_dispatch":
            continue
        if run.get("head_branch") != ref:
            continue
        created_at = str(run.get("created_at") or "")
        if not created_at:
            continue
        if _parse_github_datetime(created_at) < earliest:
            continue
        return run
    return None


async def _dispatch_workflow(
    client: AsyncGitHubClient,
    *,
    config: RemoteBuildStepConfig,
    token: str,
) -> None:
    response = await client.post(
        f"{_workflow_url(config.repository, config.workflow_id)}/dispatches",
        headers=_headers(token),
        json={"ref": config.ref},
    )
    if response.status_code != HTTP_NO_CONTENT:
        msg = f"GitHub workflow dispatch failed: HTTP {response.status_code}"
        raise GitHubActionsClientError(msg)


async def _find_dispatched_run(
    client: AsyncGitHubClient,
    *,
    config: RemoteBuildStepConfig,
    token: str,
    started_at: datetime,
) -> dict[str, Any] | None:
    response = await client.get(
        f"{_workflow_url(config.repository, config.workflow_id)}/runs",
        headers=_headers(token),
        params={
            "event": "workflow_dispatch",
            "branch": config.ref,
            "per_page": 20,
        },
    )
    response.raise_for_status()
    payload = response.json()
    runs = payload.get("workflow_runs", [])
    if not isinstance(runs, list):
        return None
    return _match_workflow_run(runs, ref=config.ref, started_at=started_at)


async def _get_run(
    client: AsyncGitHubClient,
    *,
    repository: str,
    run_id: int,
    token: str,
) -> dict[str, Any]:
    response = await client.get(
        _run_url(repository, run_id),
        headers=_headers(token),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        msg = "GitHub workflow run payload is invalid"
        raise GitHubActionsClientError(msg)
    return payload


def _completed_result(run: dict[str, Any]) -> WorkflowRunResult:
    conclusion = run.get("conclusion")
    html_url = str(run.get("html_url") or "")
    ok = conclusion == "success"
    conclusion_text = str(conclusion or "unknown")
    return WorkflowRunResult(
        ok=ok,
        status=str(run.get("status") or "completed"),
        conclusion=conclusion_text,
        html_url=html_url,
        message=(
            "GitHub workflow completed successfully"
            if ok
            else f"GitHub workflow completed with conclusion: {conclusion_text}"
        ),
    )


async def trigger_and_wait_workflow(
    config: RemoteBuildStepConfig,
    *,
    token: str,
    client: AsyncGitHubClient | None = None,
) -> WorkflowRunResult:
    started_at = datetime.now(timezone.utc)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, read=60.0),
        )

    try:
        await _dispatch_workflow(client, config=config, token=token)
        deadline = started_at + timedelta(seconds=config.timeout_seconds)
        matched_run_id: int | None = None
        last_run_url = (
            f"https://github.com/{config.repository}/actions/workflows/"
            f"{config.workflow_id}"
        )

        while datetime.now(timezone.utc) < deadline:
            if matched_run_id is None:
                matched_run = await _find_dispatched_run(
                    client,
                    config=config,
                    token=token,
                    started_at=started_at,
                )
                if matched_run is None:
                    await asyncio.sleep(config.poll_interval_seconds)
                    continue
                matched_run_id = int(matched_run["id"])
                last_run_url = str(matched_run.get("html_url") or last_run_url)

            run = await _get_run(
                client,
                repository=config.repository,
                run_id=matched_run_id,
                token=token,
            )
            last_run_url = str(run.get("html_url") or last_run_url)
            if run.get("status") == "completed":
                return _completed_result(run)
            await asyncio.sleep(config.poll_interval_seconds)

        return WorkflowRunResult(
            ok=False,
            status="timeout",
            conclusion=None,
            html_url=last_run_url,
            message="GitHub workflow timed out",
        )
    finally:
        if owns_client:
            await client.aclose()  # type: ignore[attr-defined]


__all__ = [
    "GitHubActionsClientError",
    "WorkflowRunResult",
    "trigger_and_wait_workflow",
]
