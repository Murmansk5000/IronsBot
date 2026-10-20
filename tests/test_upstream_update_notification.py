from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from scripts import notify_upstream_updates as notifier

HEAD = "a" * 40
PREVIOUS_HEAD = "b" * 40
REPOSITORY = "example/project"
ISSUE_NUMBER = 42


class GitHub:
    def __init__(self, issues: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues or []
        self.created: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, token: str, data: Any = None) -> Any:
        assert token == "test-token"
        self.calls.append((method, path))
        if method == "GET":
            page = int(parse_qs(urlsplit(path).query)["page"][0])
            return self.issues[(page - 1) * 100 : page * 100]
        assert method == "POST" and path == f"/repos/{REPOSITORY}/issues"
        issue = {**data, "number": ISSUE_NUMBER, "state": "open"}
        self.created.append(issue)
        self.issues.insert(0, issue)
        return issue


def prepare(
    monkeypatch: pytest.MonkeyPatch,
    api: GitHub,
    *,
    count: int = 1,
    subject: str = "fix: upstream change",
) -> None:
    def git(*args: str) -> str:
        if args == ("rev-parse", "upstream/main"):
            return HEAD
        if args == ("rev-list", "--count", f"HEAD..{HEAD}"):
            return str(count)
        assert args == (
            "log",
            "--max-count=50",
            "--format=%H%x09%s",
            f"HEAD..{HEAD}",
        )
        return f"{HEAD}\t{subject}"

    monkeypatch.setattr(notifier, "git", git)
    monkeypatch.setattr(notifier, "github_request", api.request)


def test_up_to_date_does_not_contact_github(monkeypatch: pytest.MonkeyPatch) -> None:
    api = GitHub()
    prepare(monkeypatch, api, count=0)
    assert notifier.notify(REPOSITORY, "test-token") is None
    assert api.calls == []


def test_new_revision_creates_assigned_issue_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = GitHub()
    prepare(monkeypatch, api)
    assert notifier.notify(REPOSITORY, "test-token") == ISSUE_NUMBER
    assert notifier.notify(REPOSITORY, "test-token") is None
    assert len(api.created) == 1
    issue = api.created[0]
    assert issue["assignees"] == ["example"]
    assert issue["body"].startswith(f"<!-- ironsbot-upstream-update:{HEAD} -->\n")
    assert f"https://github.com/Nattsu39/IronsBot/commit/{HEAD}" in issue["body"]
    assert "fix: upstream change" in issue["body"]


@pytest.mark.parametrize("state", ["open", "closed"])
def test_reported_revision_is_not_repeated(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    api = GitHub(
        [
            {
                "number": 1,
                "state": state,
                "body": f"<!-- ironsbot-upstream-update:{HEAD} -->\nold",
            }
        ]
    )
    prepare(monkeypatch, api)
    assert notifier.notify(REPOSITORY, "test-token") is None
    assert api.created == []
    query = parse_qs(urlsplit(api.calls[0][1]).query)
    assert query["state"] == ["all"]
    assert query["creator"] == ["github-actions[bot]"]


def test_new_head_is_reported_even_with_old_open_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = GitHub(
        [
            {
                "number": 1,
                "body": f"<!-- ironsbot-upstream-update:{PREVIOUS_HEAD} -->\nold",
            }
        ]
    )
    prepare(monkeypatch, api)
    assert notifier.notify(REPOSITORY, "test-token") == ISSUE_NUMBER


def test_deduplication_follows_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    api = GitHub(
        [{"number": 1, "body": "unrelated"}] * 100
        + [{"number": 2, "body": f"<!-- ironsbot-upstream-update:{HEAD} -->\nold"}]
    )
    prepare(monkeypatch, api)
    assert notifier.notify(REPOSITORY, "test-token") is None
    assert [parse_qs(urlsplit(path).query)["page"] for _, path in api.calls] == [
        ["1"],
        ["2"],
    ]
    assert api.created == []


def test_subjects_cannot_create_mentions_or_markdown_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = GitHub()
    prepare(
        monkeypatch,
        api,
        count=51,
        subject="@someone [`title`](unsafe) <tag>" + "x" * 300,
    )
    notifier.notify(REPOSITORY, "test-token")
    body = api.created[0]["body"]
    assert "@someone" not in body
    assert "[`title`]" not in body
    assert "<tag>" not in body
    assert "仅列出最近 50 个提交" in body
    assert "x" * 161 not in body


def test_api_failure_is_not_silently_treated_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = GitHub()
    prepare(monkeypatch, api)

    def unavailable(*_args: object) -> None:
        message = "GitHub unavailable"
        raise RuntimeError(message)

    monkeypatch.setattr(notifier, "github_request", unavailable)
    with pytest.raises(RuntimeError, match="GitHub unavailable"):
        notifier.notify(REPOSITORY, "test-token")


def test_retry_after_uncertain_creation_does_not_duplicate_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = GitHub()
    prepare(monkeypatch, api)

    def lost_response(method: str, path: str, token: str, data: Any = None) -> Any:
        result = api.request(method, path, token, data)
        if method == "POST":
            message = "Response lost after creation"
            raise RuntimeError(message)
        return result

    monkeypatch.setattr(notifier, "github_request", lost_response)
    with pytest.raises(RuntimeError, match="Response lost"):
        notifier.notify(REPOSITORY, "test-token")
    assert notifier.notify(REPOSITORY, "test-token") is None
    assert len(api.created) == 1


def test_workflow_schedule_and_notification_permissions() -> None:
    path = Path(__file__).resolve().parents[1] / ".github/workflows/sync-upstream.yml"
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert workflow["on"]["schedule"] == [{"cron": "0 4 * * *"}]
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    job = workflow["jobs"]["check-upstream"]
    assert job["permissions"] == {"contents": "read", "issues": "write"}
    assert job["steps"][-1]["run"] == "python scripts/notify_upstream_updates.py"
