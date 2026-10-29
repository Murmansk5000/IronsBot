# SPDX-License-Identifier: MIT
"""Append exact source snapshots while preserving both repositories' histories.

``sync_history`` accepts local origin remotes for integration use. The CLI first
requires the policy's exact GitHub origins. No worktree or branch is checked out.
Use full (not shallow) repositories; every Git invocation has a finite timeout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

TARGET_NAME = "Murmansk5000/IronsBot-History-Archive"
PUBLIC_NAME = "Murmansk5000/IronsBot"
PRIVATE_NAME = "Murmansk5000/ironsbot-private"
GIT_TIMEOUT = 120
MAX_ATTEMPTS = 10
MISSING_REF_EXIT = 2
PORCELAIN_FIELDS = 3
PROVENANCE_PREFIX = "Archive-Provenance: "
ARCHIVE_NAME = "IronsBot History Archive"
ARCHIVE_EMAIL = "archive@ironsbot.invalid"


@dataclass(frozen=True)
class ArchivePolicy:
    target_name: str
    target_branch: str
    initial_parent: str | None = None


POLICIES = {
    (PUBLIC_NAME, "main"): ArchivePolicy(TARGET_NAME, "main"),
    (PRIVATE_NAME, "main"): ArchivePolicy(
        PRIVATE_NAME,
        "archive/original-main",
        "d5ae8259960477f1fc6f6c6998cac0bdd23921d2",
    ),
    (PRIVATE_NAME, "details"): ArchivePolicy(
        PRIVATE_NAME,
        "archive/original-details",
        "4d030c67e85ef18f86c2964625b748a732cb82f2",
    ),
}


@dataclass(frozen=True)
class ArchiveResult:
    archive_sha: str
    source_sha: str
    source_tree: str
    target_branch: str
    status: str
    attempts: int


class RetryExhaustedError(RuntimeError):
    """Source movement or target contention exhausted the bounded attempts."""


def git(
    repo: Path,
    *args: str,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Run bounded Git, returning stdout and propagating failures verbatim."""
    environment = os.environ.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["LC_ALL"] = "C"
    if env is not None:
        environment.update(env)
    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
        timeout=GIT_TIMEOUT,
        check=True,
        env=environment,
    )
    return completed.stdout.strip()


def policy_for(source_name: str, source_branch: str) -> ArchivePolicy:
    """Reject every source/branch pair not explicitly permitted by policy."""
    try:
        return POLICIES[source_name, source_branch]
    except KeyError as exc:
        message = f"Unsupported archive source: {source_name}/{source_branch}"
        raise ValueError(message) from exc


def validate_origin(repo: Path, expected_name: str) -> None:
    """Require all effective origin fetch/push URLs to name exactly one repo."""
    pattern = re.compile(
        rf"(?:https://github\.com/|git@github\.com:)"
        rf"{re.escape(expected_name)}(?:\.git)?/?"
    )
    for options in (("--all",), ("--push", "--all")):
        urls = git(repo, "remote", "get-url", *options, "origin").splitlines()
        if not urls or any(pattern.fullmatch(url) is None for url in urls):
            message = f"Origin for {repo} must name exactly {expected_name}"
            raise ValueError(message)


def validate_origins(
    source_repo: Path, target_repo: Path, source_name: str, source_branch: str
) -> None:
    """Validate the CLI policy and both fetch and push destinations."""
    policy = policy_for(source_name, source_branch)
    validate_origin(source_repo, source_name)
    validate_origin(target_repo, policy.target_name)


def fetch_branch(repo: Path, branch: str) -> str | None:
    """Fetch a branch into an isolated temporary ref, never a checkout branch.

    A missing branch returns None; transport, permission and fetch errors do not.
    The '+' permits fetching upstream rewrites, not force-pushing any history.
    """
    remote_ref = f"refs/heads/{branch}"
    try:
        git(repo, "ls-remote", "--exit-code", "--heads", "origin", remote_ref)
    except subprocess.CalledProcessError as exc:
        if exc.returncode == MISSING_REF_EXIT:
            return None
        raise
    temporary_ref = f"refs/archive-history/{uuid4().hex}"
    try:
        git(
            repo,
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            "--refmap=",
            "origin",
            f"+{remote_ref}:{temporary_ref}",
        )
        return git(repo, "rev-parse", "--verify", f"{temporary_ref}^{{commit}}")
    finally:
        git(repo, "update-ref", "-d", temporary_ref)


def import_commit(target_repo: Path, source_repo: Path, sha: str) -> None:
    """Import the exact object graph without modifying original commits/refs."""
    git(
        target_repo,
        "fetch",
        "--no-tags",
        "--no-write-fetch-head",
        "--refmap=",
        str(source_repo.resolve()),
        sha,
    )


def provenance(
    source_name: str, source_branch: str, source_sha: str, tree: str
) -> dict[str, str | None]:
    policy = policy_for(source_name, source_branch)
    return {
        "source_repo": source_name,
        "source_branch": source_branch,
        "source_sha": source_sha,
        "tree": tree,
        "target_repo": policy.target_name,
        "target_branch": policy.target_branch,
        "initial_parent": policy.initial_parent,
    }


def is_archived(target_repo: Path, head: str, expected: dict[str, str | None]) -> bool:
    """Only exact, unambiguous structured provenance plus tree is a duplicate."""
    message = git(target_repo, "show", "-s", "--format=%B", head)
    records = [
        line.removeprefix(PROVENANCE_PREFIX)
        for line in message.splitlines()
        if line.startswith(PROVENANCE_PREFIX)
    ]
    if len(records) != 1:
        return False
    try:
        matches = json.loads(records[0]) == expected
    except json.JSONDecodeError:
        return False
    return (
        matches
        and git(target_repo, "rev-parse", f"{head}^{{tree}}") == expected["tree"]
    )


def build_archive_commit(
    target_repo: Path, parent: str, record: dict[str, str | None]
) -> str:
    """Build and verify a synthetic commit, retaining both parent histories."""
    source_sha = str(record["source_sha"])
    tree = str(record["tree"])
    initial = record["initial_parent"] or "existing target main (must exist)"
    source = f"{record['source_repo']}:{record['source_branch']}"
    target = f"{record['target_repo']}:{record['target_branch']}"
    message = (
        f"chore(archive): preserve {source} at {source_sha}\n\n"
        "Why: Preserve the current source snapshot and all prior archive history.\n"
        "原因: 保留当前来源快照和全部既有归档历史。\n\n"
        f"Scope: Source {source}; commit {source_sha}; tree {tree}; "
        f"target {target}; prior parent {parent}; original initial parent {initial}.\n"
        f"范围: 来源 {source}；提交 {source_sha}；树 {tree}；"
        f"目标 {target}；前序父提交 {parent}；原始初始父提交 {initial}。\n\n"
        "Verification: Exact source tree and ancestry of both parents verified.\n"
        "验证: 已验证来源树完全一致且两个父提交均为祖先。\n\n"
        f"{PROVENANCE_PREFIX}{json.dumps(record, sort_keys=True)}\n"
    )
    identity = {
        "GIT_AUTHOR_NAME": ARCHIVE_NAME,
        "GIT_AUTHOR_EMAIL": ARCHIVE_EMAIL,
        "GIT_COMMITTER_NAME": ARCHIVE_NAME,
        "GIT_COMMITTER_EMAIL": ARCHIVE_EMAIL,
        "GIT_AUTHOR_DATE": "",
        "GIT_COMMITTER_DATE": "",
    }
    commit = git(
        target_repo,
        "commit-tree",
        tree,
        "-p",
        parent,
        "-p",
        source_sha,
        input_text=message,
        env=identity,
    )
    if git(target_repo, "rev-parse", f"{commit}^{{tree}}") != tree:
        message = "Archive tree differs from source"
        raise RuntimeError(message)
    for ancestor in (parent, source_sha):
        git(target_repo, "merge-base", "--is-ancestor", ancestor, commit)
    return commit


def _initial_parent(source_repo: Path, target_repo: Path, policy: ArchivePolicy) -> str:
    if policy.initial_parent is None:
        message = "The public archive main branch must already exist"
        raise ValueError(message)
    # Fetch the fixed original root even after the source has rewritten history.
    git(
        source_repo,
        "fetch",
        "--no-tags",
        "--no-write-fetch-head",
        "--refmap=",
        "origin",
        policy.initial_parent,
    )
    import_commit(target_repo, source_repo, policy.initial_parent)
    return policy.initial_parent


def _concurrent_rejection(error: subprocess.CalledProcessError) -> bool:
    reasons = {
        "[rejected] (fetch first)",
        "[rejected] (non-fast-forward)",
        "[remote rejected] (failed to update ref)",
    }
    return any(
        len(fields := line.split("\t")) == PORCELAIN_FIELDS
        and fields[0] == "!"
        and fields[2] in reasons
        for line in (error.stdout or "").splitlines()
    )


def _push_archive(target_repo: Path, branch: str, commit: str, old: str | None) -> bool:
    """Return False only for a confirmed concurrent target ref update."""
    try:
        git(
            target_repo,
            "-c",
            "remote.origin.mirror=false",
            "push",
            "--porcelain",
            "--no-follow-tags",
            "--recurse-submodules=no",
            "origin",
            f"{commit}:refs/heads/{branch}",
        )
    except subprocess.CalledProcessError as exc:
        if not _concurrent_rejection(exc):
            raise
        current = fetch_branch(target_repo, branch)
        if current is None or current == old:
            raise
        if old is not None:
            git(target_repo, "merge-base", "--is-ancestor", old, current)
        return False
    return True


def sync_history(
    source_repo: Path,
    target_repo: Path,
    source_name: str,
    source_branch: str,
    *,
    attempts: int = 3,
) -> ArchiveResult:
    """Append current origin history; retry only source movement or ref races.

    Local bare origins are supported here, not by CLI validation. A final source
    refresh is made immediately before pushing (or returning a duplicate).
    Cross-repository atomicity is impossible: a later source change requires a
    subsequent run. No stale event SHA or event checkout is ever trusted.
    """
    policy = policy_for(source_name, source_branch)
    if not 1 <= attempts <= MAX_ATTEMPTS:
        message = f"attempts must be between 1 and {MAX_ATTEMPTS}"
        raise ValueError(message)
    for repo in (source_repo, target_repo):
        if git(repo, "rev-parse", "--is-shallow-repository") != "false":
            message = "Archive sync requires full, non-shallow repositories"
            raise ValueError(message)
    for attempt in range(1, attempts + 1):
        source_sha = fetch_branch(source_repo, source_branch)
        if source_sha is None:
            message = f"Source branch is missing: {source_branch}"
            raise ValueError(message)
        import_commit(target_repo, source_repo, source_sha)
        tree = git(target_repo, "rev-parse", f"{source_sha}^{{tree}}")
        old = fetch_branch(target_repo, policy.target_branch)
        parent = old or _initial_parent(source_repo, target_repo, policy)
        record = provenance(source_name, source_branch, source_sha, tree)
        duplicate = old is not None and is_archived(target_repo, old, record)
        commit = old if duplicate else build_archive_commit(target_repo, parent, record)
        if fetch_branch(source_repo, source_branch) != source_sha:
            continue
        if duplicate:
            git(target_repo, "merge-base", "--is-ancestor", source_sha, str(commit))
            return ArchiveResult(
                str(commit),
                source_sha,
                tree,
                policy.target_branch,
                "unchanged",
                attempt,
            )
        if _push_archive(target_repo, policy.target_branch, str(commit), old):
            return ArchiveResult(
                str(commit), source_sha, tree, policy.target_branch, "appended", attempt
            )
    message = "Archive retries exhausted by source movement or target contention"
    raise RetryExhaustedError(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--target-repo", type=Path, required=True)
    parser.add_argument(
        "--source-name", choices=(PUBLIC_NAME, PRIVATE_NAME), required=True
    )
    parser.add_argument("--source-branch", choices=("main", "details"), required=True)
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args(argv)
    validate_origins(
        args.source_repo, args.target_repo, args.source_name, args.source_branch
    )
    result = sync_history(
        args.source_repo,
        args.target_repo,
        args.source_name,
        args.source_branch,
        attempts=args.attempts,
    )
    sys.stdout.write(json.dumps(asdict(result), sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
