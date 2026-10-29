from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str) -> dict:
    path = ROOT / ".github/workflows" / name
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_public_archive_only_trusts_main_pushes() -> None:
    workflow = _workflow("archive-history.yml")
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert "pull_request" not in workflow["on"]
    assert workflow["permissions"]["contents"] == "read"
    job = workflow["jobs"]["archive"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert job["uses"] == "./.github/workflows/archive-history-reusable.yml"
    assert job["with"]["tooling_revision"] == "${{ github.sha }}"
    assert job["secrets"]["archive_deploy_key"] == (
        "${{ secrets.HISTORY_ARCHIVE_SSH_KEY }}"
    )


def test_reusable_archive_pins_tooling_and_serializes_targets() -> None:
    workflow = _workflow("archive-history-reusable.yml")
    assert set(workflow["on"]) == {"workflow_call"}
    assert "permissions" not in workflow
    job = workflow["jobs"]["archive"]
    assert "github.repository" in job["if"]
    assert "refs/heads/main" in job["if"]
    assert "inputs.source_branch == 'details'" in job["if"]
    assert job["concurrency"]["cancel-in-progress"] == "false"
    steps = job["steps"]
    tooling = next(s for s in steps if s["name"] == "Checkout pinned archive tooling")
    assert tooling["with"]["ref"] == "${{ inputs.tooling_revision }}"
    target = next(s for s in steps if s["name"] == "Checkout cumulative archive")
    assert target["with"]["ssh-strict"] == "true"
    assert target["with"]["fetch-depth"] == "0"
    append = next(s for s in steps if s["name"] == "Append verified source snapshot")
    assert append["shell"] == "bash"
    assert "set -euo pipefail" in append["run"]
    assert '--source-name "$SOURCE_NAME"' in append["run"]
    assert '--source-branch "$SOURCE_BRANCH"' in append["run"]
    assert "--attempts 3" in append["run"]
    assert "--force" not in append["run"]
