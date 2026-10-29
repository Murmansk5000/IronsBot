# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pytest

from scripts import archive_history as archive

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest import CaptureFixture, MonkeyPatch

ORIGINAL_GIT = archive.git
HISTORICAL_IDENTITY = {
    "GIT_AUTHOR_NAME": "Original Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_COMMITTER_NAME": "Original Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.invalid",
    "GIT_AUTHOR_DATE": "2001-02-03T04:05:06+08:00",
    "GIT_COMMITTER_DATE": "2002-03-04T05:06:07-03:00",
}


@pytest.fixture(autouse=True)
def isolate_git_configuration(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)


def make_commit(
    repo: Path, message: str, *, parent: str | None = None, tree: str | None = None
) -> str:
    if tree is None:
        blob = ORIGINAL_GIT(repo, "hash-object", "-w", "--stdin", input_text=message)
        tree = ORIGINAL_GIT(
            repo, "mktree", input_text=f"100644 blob {blob}\tfile.txt\n"
        )
    parents = ("-p", parent) if parent is not None else ()
    return ORIGINAL_GIT(
        repo,
        "commit-tree",
        tree,
        *parents,
        input_text=message,
        env=HISTORICAL_IDENTITY,
    )


def init_repo(path: Path, *, bare: bool = False) -> Path:
    path.mkdir()
    ORIGINAL_GIT(path, "init", "--initial-branch=main", *(("--bare",) if bare else ()))
    return path


@dataclass
class Repositories:
    root: Path
    source: Path
    target: Path
    source_origin: Path
    target_origin: Path
    source_root: str
    target_root: str

    def sync(self, *, attempts: int = 3) -> archive.ArchiveResult:
        return archive.sync_history(
            self.source,
            self.target,
            archive.PUBLIC_NAME,
            "main",
            attempts=attempts,
        )

    def advance(
        self, message: str, *, parent: str | None = None, tree: str | None = None
    ) -> str:
        if parent is None:
            parent = self.tip(self.source_origin)
        sha = make_commit(self.source, message, parent=parent, tree=tree)
        self.publish(sha)
        return sha

    def publish(self, sha: str, branch: str = "main") -> None:
        # Only test fixture remotes are rewritten, never the user's repositories.
        ORIGINAL_GIT(
            self.source, "push", "--force", "origin", f"{sha}:refs/heads/{branch}"
        )

    def tip(self, repo: Path | None = None, branch: str = "main") -> str:
        return ORIGINAL_GIT(
            repo or self.target_origin, "rev-parse", f"refs/heads/{branch}"
        )

    def competitor(self) -> Path:
        path = init_repo(self.root / "competitor")
        ORIGINAL_GIT(path, "remote", "add", "origin", str(self.target_origin))
        return path

    def assert_snapshot(self, result: archive.ArchiveResult, old: str) -> None:
        assert self.tip(branch=result.target_branch) == result.archive_sha
        assert result.source_tree == ORIGINAL_GIT(
            self.source, "rev-parse", f"{result.source_sha}^{{tree}}"
        )
        assert result.source_tree == ORIGINAL_GIT(
            self.target_origin, "rev-parse", f"{result.archive_sha}^{{tree}}"
        )
        for parent in (old, result.source_sha):
            ORIGINAL_GIT(
                self.target_origin,
                "merge-base",
                "--is-ancestor",
                parent,
                result.archive_sha,
            )


@pytest.fixture
def repos(tmp_path: Path) -> Repositories:
    source_origin = init_repo(tmp_path / "source.git", bare=True)
    target_origin = init_repo(tmp_path / "history.git", bare=True)
    source = init_repo(tmp_path / "source")
    target = init_repo(tmp_path / "history")
    ORIGINAL_GIT(source, "remote", "add", "origin", str(source_origin))
    ORIGINAL_GIT(target, "remote", "add", "origin", str(target_origin))
    source_root = make_commit(source, "original source root")
    target_root = make_commit(target, "original target root")
    ORIGINAL_GIT(source, "update-ref", "refs/heads/main", source_root)
    ORIGINAL_GIT(target, "update-ref", "refs/heads/main", target_root)
    ORIGINAL_GIT(source, "push", "origin", "main")
    ORIGINAL_GIT(target, "push", "origin", "main")
    return Repositories(
        tmp_path, source, target, source_origin, target_origin, source_root, target_root
    )


def test_first_sync_keeps_roots_identity_dates_and_checkouts(
    repos: Repositories,
) -> None:
    original = ORIGINAL_GIT(repos.source, "cat-file", "commit", repos.source_root)
    result = repos.sync()
    assert result.status == "appended"
    repos.assert_snapshot(result, repos.target_root)
    assert ORIGINAL_GIT(
        repos.target_origin, "show", "-s", "--format=%P", result.archive_sha
    ).split() == [repos.target_root, repos.source_root]
    assert (
        ORIGINAL_GIT(repos.target_origin, "cat-file", "commit", repos.source_root)
        == original
    )
    assert "author Original Author <author@example.invalid>" in original
    assert "+0800" in original
    assert "-0300" in original
    assert ORIGINAL_GIT(repos.source, "rev-parse", "HEAD") == repos.source_root
    assert ORIGINAL_GIT(repos.target, "rev-parse", "HEAD") == repos.target_root
    assert ORIGINAL_GIT(repos.source, "for-each-ref", "refs/archive-history") == ""
    assert ORIGINAL_GIT(repos.target, "for-each-ref", "refs/archive-history") == ""
    identity = ORIGINAL_GIT(
        repos.target_origin,
        "show",
        "-s",
        "--format=%an <%ae>%n%cn <%ce>",
        result.archive_sha,
    )
    expected_identity = f"{archive.ARCHIVE_NAME} <{archive.ARCHIVE_EMAIL}>"
    assert identity.splitlines() == [expected_identity, expected_identity]
    body = ORIGINAL_GIT(
        repos.target_origin, "show", "-s", "--format=%B", result.archive_sha
    )
    for value in (
        "chore(archive):",
        "Why:",
        "原因:",
        "Scope:",
        "范围:",
        "Verification:",
        "验证:",
        archive.PUBLIC_NAME,
        result.source_sha,
        result.source_tree,
        repos.target_root,
        "existing target main",
    ):
        assert value in body
    assert "tests" not in body.lower()
    assert "CI" not in body


def test_exact_tree_with_binary_executable_and_symlink(repos: Repositories) -> None:
    binary = repos.source / "binary.dat"
    binary.write_bytes(bytes(range(256)))
    blob = ORIGINAL_GIT(repos.source, "hash-object", "-w", str(binary))
    link = ORIGINAL_GIT(
        repos.source, "hash-object", "-w", "--stdin", input_text="binary.dat"
    )
    tree = ORIGINAL_GIT(
        repos.source,
        "mktree",
        input_text=(
            f"100644 blob {blob}\tbinary.dat\n"
            f"100755 blob {blob}\texecutable\n"
            f"120000 blob {link}\tlink\n"
        ),
    )
    sha = repos.advance("binary and modes", tree=tree)
    result = repos.sync()
    assert result.source_sha == sha
    assert result.source_tree == tree
    repos.assert_snapshot(result, repos.target_root)
    assert ORIGINAL_GIT(repos.source, "ls-tree", "-r", sha) == ORIGINAL_GIT(
        repos.target_origin, "ls-tree", "-r", result.archive_sha
    )


def test_changes_and_multiple_commits_all_remain_ancestors(repos: Repositories) -> None:
    first = repos.sync()
    second_source = repos.advance("second source")
    third_source = repos.advance("third source")
    second = repos.sync()
    repos.assert_snapshot(second, first.archive_sha)
    assert second.source_sha == third_source
    ORIGINAL_GIT(
        repos.target_origin,
        "merge-base",
        "--is-ancestor",
        second_source,
        second.archive_sha,
    )
    assert second.archive_sha != first.archive_sha


def test_duplicate_is_noop_but_same_tree_new_sha_appends(repos: Repositories) -> None:
    first = repos.sync()
    duplicate = repos.sync()
    assert duplicate.status == "unchanged"
    assert duplicate.archive_sha == first.archive_sha
    new_source = repos.advance("empty change", tree=first.source_tree)
    result = repos.sync()
    assert result.status == "appended"
    assert result.source_sha == new_source
    assert result.source_tree == first.source_tree
    assert result.archive_sha != first.archive_sha
    repos.assert_snapshot(result, first.archive_sha)


@pytest.mark.parametrize("rewind", [False, True])
def test_source_force_rewrite_or_rewind_preserves_archive(
    repos: Repositories, *, rewind: bool
) -> None:
    repos.advance("old source advance")
    first = repos.sync()
    current = (
        repos.source_root if rewind else make_commit(repos.source, "unrelated root")
    )
    repos.publish(current)
    result = repos.sync()
    assert result.source_sha == current
    repos.assert_snapshot(result, first.archive_sha)
    ORIGINAL_GIT(
        repos.target_origin,
        "merge-base",
        "--is-ancestor",
        first.source_sha,
        result.archive_sha,
    )


def test_stale_checkout_never_overwrites_current_source(repos: Repositories) -> None:
    latest = repos.advance("latest remote, old event checkout")
    result = repos.sync()
    assert ORIGINAL_GIT(repos.source, "rev-parse", "HEAD") == repos.source_root
    assert result.source_sha == latest
    repos.assert_snapshot(result, repos.target_root)


def test_source_refresh_immediately_before_push(
    repos: Repositories, monkeypatch: MonkeyPatch
) -> None:
    original_build = archive.build_archive_commit
    advanced: list[str] = []

    def build(target: Path, parent: str, record: dict[str, str | None]) -> str:
        commit = original_build(target, parent, record)
        if not advanced:
            advanced.append(repos.advance("source changed while building"))
        return commit

    monkeypatch.setattr(archive, "build_archive_commit", build)
    result = repos.sync()
    assert result.source_sha == advanced[0]
    assert result.attempts == 2  # noqa: PLR2004
    repos.assert_snapshot(result, repos.target_root)
    assert (
        ORIGINAL_GIT(
            repos.target_origin, "show", "-s", "--format=%P", result.archive_sha
        ).split()[0]
        == repos.target_root
    )


def test_duplicate_also_refreshes_source_before_return(
    repos: Repositories, monkeypatch: MonkeyPatch
) -> None:
    first = repos.sync()
    original_match = archive.is_archived
    advanced: list[str] = []

    def match(target: Path, head: str, record: dict[str, str | None]) -> bool:
        result = original_match(target, head, record)
        if not advanced:
            advanced.append(repos.advance("moved during no-op check"))
        return result

    monkeypatch.setattr(archive, "is_archived", match)
    result = repos.sync()
    assert result.status == "appended"
    assert result.source_sha == advanced[0]
    repos.assert_snapshot(result, first.archive_sha)


def intercept_push(
    monkeypatch: MonkeyPatch, before_push: Callable[[], None]
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def run(
        repo: Path,
        *args: str,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        calls.append(args)
        if "push" in args:
            before_push()
        return ORIGINAL_GIT(repo, *args, input_text=input_text, env=env)

    monkeypatch.setattr(archive, "git", run)
    return calls


def test_concurrent_archive_same_source_does_not_duplicate(
    repos: Repositories, monkeypatch: MonkeyPatch
) -> None:
    competitor = repos.competitor()
    competing: list[archive.ArchiveResult] = []

    def race() -> None:
        if competing:
            return
        # Distinct prior target tip makes this race deterministic across seconds.
        parent = archive.fetch_branch(competitor, "main")
        extra = make_commit(competitor, "another target append", parent=parent)
        ORIGINAL_GIT(competitor, "push", "origin", f"{extra}:refs/heads/main")
        with monkeypatch.context() as context:
            context.setattr(archive, "git", ORIGINAL_GIT)
            competing.append(
                archive.sync_history(
                    repos.source, competitor, archive.PUBLIC_NAME, "main"
                )
            )

    calls = intercept_push(monkeypatch, race)
    result = repos.sync()
    assert result.status == "unchanged"
    assert result.archive_sha == competing[0].archive_sha
    assert result.attempts == 2  # noqa: PLR2004
    assert len([call for call in calls if "push" in call]) == 1
    repos.assert_snapshot(result, repos.target_root)


def test_concurrent_target_and_new_source_rebuild_on_latest_target(
    repos: Repositories, monkeypatch: MonkeyPatch
) -> None:
    competitor = repos.competitor()
    competing: list[archive.ArchiveResult] = []
    latest: list[str] = []

    def race() -> None:
        if competing:
            return
        latest.append(repos.advance("new source during concurrent push"))
        with monkeypatch.context() as context:
            context.setattr(archive, "git", ORIGINAL_GIT)
            competing.append(
                archive.sync_history(
                    repos.source, competitor, archive.PUBLIC_NAME, "main"
                )
            )
        latest.append(repos.advance("newest source after competing archive"))

    intercept_push(monkeypatch, race)
    result = repos.sync()
    assert result.status == "appended"
    assert result.source_sha == latest[-1]
    repos.assert_snapshot(result, competing[0].archive_sha)


def test_retry_exhaustion_never_loses_concurrent_target(
    repos: Repositories, monkeypatch: MonkeyPatch
) -> None:
    competitor = repos.competitor()
    tips: list[str] = []

    def race() -> None:
        parent = archive.fetch_branch(competitor, "main")
        commit = make_commit(competitor, f"competing append {len(tips)}", parent=parent)
        ORIGINAL_GIT(competitor, "push", "origin", f"{commit}:refs/heads/main")
        tips.append(commit)

    intercept_push(monkeypatch, race)
    with pytest.raises(archive.RetryExhaustedError):
        repos.sync(attempts=2)
    assert len(tips) == 2  # noqa: PLR2004
    assert repos.tip() == tips[-1]
    for tip in [repos.target_root, *tips]:
        ORIGINAL_GIT(
            repos.target_origin, "merge-base", "--is-ancestor", tip, repos.tip()
        )


def test_continuous_source_movement_is_bounded_without_push(
    repos: Repositories, monkeypatch: MonkeyPatch
) -> None:
    original_build = archive.build_archive_commit

    def build(target: Path, parent: str, record: dict[str, str | None]) -> str:
        commit = original_build(target, parent, record)
        repos.advance(f"moved after {record['source_sha']}")
        return commit

    monkeypatch.setattr(archive, "build_archive_commit", build)
    with pytest.raises(archive.RetryExhaustedError):
        repos.sync(attempts=2)
    assert repos.tip() == repos.target_root


@pytest.mark.parametrize(
    "reason", ["[remote rejected] (pre-receive hook declined)", "authentication failed"]
)
def test_non_concurrency_push_errors_propagate(
    repos: Repositories, monkeypatch: MonkeyPatch, reason: str
) -> None:
    pushes: list[tuple[str, ...]] = []

    def run(
        repo: Path,
        *args: str,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        if "push" in args:
            pushes.append(args)
            raise subprocess.CalledProcessError(
                1, args, output=f"!\tsha:refs/heads/main\t{reason}\n", stderr=reason
            )
        return ORIGINAL_GIT(repo, *args, input_text=input_text, env=env)

    monkeypatch.setattr(archive, "git", run)
    with pytest.raises(subprocess.CalledProcessError, match="non-zero"):
        repos.sync()
    assert len(pushes) == 1
    assert repos.tip() == repos.target_root


def test_rejection_without_target_movement_is_not_retried(
    repos: Repositories, monkeypatch: MonkeyPatch
) -> None:
    def fail() -> None:
        raise subprocess.CalledProcessError(
            1, "git push", output="!\tsha:refs/heads/main\t[rejected] (fetch first)\n"
        )

    calls = intercept_push(monkeypatch, fail)
    with pytest.raises(subprocess.CalledProcessError):
        repos.sync()
    assert len([call for call in calls if "push" in call]) == 1
    assert repos.tip() == repos.target_root


def test_push_never_forces_or_pushes_tags_or_mirrors(
    repos: Repositories, monkeypatch: MonkeyPatch
) -> None:
    ORIGINAL_GIT(repos.target, "config", "remote.origin.mirror", "true")
    ORIGINAL_GIT(repos.target, "config", "push.followTags", "true")
    ORIGINAL_GIT(
        repos.target,
        "-c",
        "user.name=Tagger",
        "-c",
        "user.email=tag@example.invalid",
        "tag",
        "-a",
        "not-for-archive",
        "-m",
        "local annotated tag",
        repos.target_root,
    )
    calls = intercept_push(monkeypatch, lambda: None)
    result = repos.sync()
    pushes = [call for call in calls if "push" in call]
    assert len(pushes) == 1
    assert "--no-follow-tags" in pushes[0]
    assert "remote.origin.mirror=false" in pushes[0]
    assert not any("force" in arg or arg.startswith("+") for arg in pushes[0])
    assert ORIGINAL_GIT(repos.target_origin, "tag", "--list") == ""
    repos.assert_snapshot(result, repos.target_root)


@pytest.mark.parametrize("damage", ["missing", "wrong-sha", "wrong-tree", "duplicate"])
def test_tree_alone_or_false_provenance_is_not_a_duplicate(
    repos: Repositories, damage: str
) -> None:
    tree = ORIGINAL_GIT(repos.source, "rev-parse", f"{repos.source_root}^{{tree}}")
    record = archive.provenance(archive.PUBLIC_NAME, "main", repos.source_root, tree)
    actual_tree = tree
    if damage == "wrong-sha":
        record["source_sha"] = repos.target_root
    if damage == "wrong-tree":
        actual_tree = ORIGINAL_GIT(
            repos.target, "rev-parse", f"{repos.target_root}^{{tree}}"
        )
    metadata = archive.PROVENANCE_PREFIX + json.dumps(record)
    message = "same tree without provenance" if damage == "missing" else metadata
    if damage == "duplicate":
        message += "\n" + metadata
    archive.import_commit(repos.target, repos.source, repos.source_root)
    false_head = make_commit(
        repos.target, message, parent=repos.target_root, tree=actual_tree
    )
    ORIGINAL_GIT(repos.target, "push", "origin", f"{false_head}:refs/heads/main")
    result = repos.sync()
    assert result.status == "appended"
    repos.assert_snapshot(result, false_head)


def test_policy_contains_exact_private_branches_and_original_parents() -> None:
    assert archive.TARGET_NAME == "Murmansk5000/IronsBot-History-Archive"
    assert archive.policy_for("Murmansk5000/IronsBot", "main") == archive.ArchivePolicy(
        "Murmansk5000/IronsBot-History-Archive", "main"
    )
    assert archive.policy_for(
        "Murmansk5000/ironsbot-private", "main"
    ) == archive.ArchivePolicy(
        "Murmansk5000/ironsbot-private",
        "archive/original-main",
        "d5ae8259960477f1fc6f6c6998cac0bdd23921d2",
    )
    assert archive.policy_for(
        "Murmansk5000/ironsbot-private", "details"
    ) == archive.ArchivePolicy(
        "Murmansk5000/ironsbot-private",
        "archive/original-details",
        "4d030c67e85ef18f86c2964625b748a732cb82f2",
    )


@pytest.mark.parametrize("branch", ["main", "details"])
def test_private_branch_first_sync_and_subsequent_append(
    repos: Repositories, monkeypatch: MonkeyPatch, branch: str
) -> None:
    original_policy = archive.policy_for(archive.PRIVATE_NAME, branch)
    repos.target_origin = repos.source_origin
    ORIGINAL_GIT(repos.target, "remote", "set-url", "origin", str(repos.source_origin))
    # Fixed production SHAs cannot be manufactured; substitute a real fixture root.
    monkeypatch.setitem(
        archive.POLICIES,
        (archive.PRIVATE_NAME, branch),
        replace(original_policy, initial_parent=repos.source_root),
    )
    sha = repos.advance(f"private {branch}")
    repos.publish(sha, branch)
    result = archive.sync_history(
        repos.source, repos.target, archive.PRIVATE_NAME, branch
    )
    assert result.target_branch == original_policy.target_branch
    assert ORIGINAL_GIT(repos.target_origin, "rev-parse", f"refs/heads/{branch}") == sha
    repos.assert_snapshot(result, repos.source_root)
    body = ORIGINAL_GIT(
        repos.target_origin, "show", "-s", "--format=%B", result.archive_sha
    )
    assert f"original initial parent {repos.source_root}" in body
    assert "target Murmansk5000/ironsbot-private:" in body
    next_sha = repos.advance("private next", parent=sha)
    repos.publish(next_sha, branch)
    next_result = archive.sync_history(
        repos.source, repos.target, archive.PRIVATE_NAME, branch
    )
    repos.assert_snapshot(next_result, result.archive_sha)
    assert repos.tip() == next_sha


def test_public_main_must_exist(repos: Repositories) -> None:
    ORIGINAL_GIT(repos.target_origin, "update-ref", "-d", "refs/heads/main")
    with pytest.raises(ValueError, match="must already exist"):
        repos.sync()
    assert archive.fetch_branch(repos.target, "main") is None


@pytest.mark.parametrize(
    ("name", "branch"),
    [
        (archive.PUBLIC_NAME, "details"),
        (archive.PRIVATE_NAME, "other"),
        ("other/IronsBot", "main"),
        ("--upload-pack=evil", "main"),
    ],
)
def test_invalid_source_policy_rejected(name: str, branch: str) -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        archive.policy_for(name, branch)


@pytest.mark.parametrize("attempts", [0, -1, archive.MAX_ATTEMPTS + 1])
def test_attempts_are_bounded_before_git(repos: Repositories, attempts: int) -> None:
    with pytest.raises(ValueError, match="attempts must"):
        repos.sync(attempts=attempts)
    assert repos.tip() == repos.target_root


@pytest.mark.parametrize(
    "url_template",
    [
        "https://github.com/{name}",
        "https://github.com/{name}.git",
        "git@github.com:{name}",
        "git@github.com:{name}.git",
    ],
)
def test_origin_allows_exact_checkout_https_and_scp(
    repos: Repositories, url_template: str
) -> None:
    for path, name in (
        (repos.source, "Murmansk5000/IronsBot"),
        (repos.target, "Murmansk5000/IronsBot-History-Archive"),
    ):
        ORIGINAL_GIT(
            path, "remote", "set-url", "origin", url_template.format(name=name)
        )
    archive.validate_origins(repos.source, repos.target, archive.PUBLIC_NAME, "main")


@pytest.mark.parametrize("branch", ["main", "details"])
@pytest.mark.parametrize("prefix", ["https://github.com/", "git@github.com:"])
def test_private_cli_accepts_same_repo_and_rejects_public_archive(
    repos: Repositories,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
    branch: str,
    prefix: str,
) -> None:
    private_url = prefix + "Murmansk5000/ironsbot-private"
    for path in (repos.source, repos.target):
        ORIGINAL_GIT(path, "remote", "set-url", "origin", private_url)
    expected_branch = "archive/original-" + branch

    def sync(
        source: Path, target: Path, name: str, source_branch: str, *, attempts: int
    ) -> archive.ArchiveResult:
        assert (source, target, name, source_branch, attempts) == (
            repos.source,
            repos.target,
            "Murmansk5000/ironsbot-private",
            branch,
            3,
        )
        return archive.ArchiveResult(
            "archive-sha", "source-sha", "tree-sha", expected_branch, "unchanged", 1
        )

    monkeypatch.setattr(archive, "sync_history", sync)
    arguments = [
        "--source-repo",
        str(repos.source),
        "--target-repo",
        str(repos.target),
        "--source-name",
        "Murmansk5000/ironsbot-private",
        "--source-branch",
        branch,
        "--attempts",
        "3",
    ]
    assert archive.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["target_branch"] == expected_branch
    ORIGINAL_GIT(
        repos.target,
        "remote",
        "set-url",
        "origin",
        prefix + "Murmansk5000/IronsBot-History-Archive",
    )
    with pytest.raises(
        ValueError, match="must name exactly Murmansk5000/ironsbot-private"
    ):
        archive.main(arguments)


@pytest.mark.parametrize(
    "bad_url",
    [
        "https://github.com/Murmansk5000/History-Archive",
        "https://github.com/other/History-Archive",
        "https://github.com/Murmansk5000/History-Archive-extra",
        "https://github.com.evil/Murmansk5000/History-Archive",
        "https://github.com/Murmansk5000/History-Archive?redirect=evil",
        "https://token@github.com/Murmansk5000/History-Archive",
        "git@other.com:Murmansk5000/History-Archive",
        "ssh://git@github.com/Murmansk5000/History-Archive",
        "https://github.com/Murmansk5000/History-Archive/other",
        "../local.git",
    ],
)
def test_origin_rejects_arbitrary_targets(repos: Repositories, bad_url: str) -> None:
    ORIGINAL_GIT(repos.target, "remote", "set-url", "origin", bad_url)
    with pytest.raises(ValueError, match="must name exactly"):
        archive.validate_origin(repos.target, archive.TARGET_NAME)


def test_origin_rejects_different_push_url_and_extra_fetch_url(
    repos: Repositories,
) -> None:
    good = f"https://github.com/{archive.TARGET_NAME}"
    ORIGINAL_GIT(repos.target, "remote", "set-url", "origin", good)
    ORIGINAL_GIT(repos.target, "remote", "set-url", "--push", "origin", "../evil.git")
    with pytest.raises(ValueError, match="must name exactly"):
        archive.validate_origin(repos.target, archive.TARGET_NAME)
    ORIGINAL_GIT(repos.target, "remote", "set-url", "--push", "origin", good)
    ORIGINAL_GIT(repos.target, "remote", "set-url", "--add", "origin", "../evil.git")
    with pytest.raises(ValueError, match="must name exactly"):
        archive.validate_origin(repos.target, archive.TARGET_NAME)


def test_cli_local_origins_rejected_without_remote_mutation(
    repos: Repositories,
) -> None:
    with pytest.raises(ValueError, match="must name exactly"):
        archive.main(
            [
                "--source-repo",
                str(repos.source),
                "--target-repo",
                str(repos.target),
                "--source-name",
                archive.PUBLIC_NAME,
                "--source-branch",
                "main",
                "--attempts",
                "3",
            ]
        )
    assert repos.tip() == repos.target_root


def test_cli_json_contract_and_validation_order(
    repos: Repositories, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def validate(source: Path, target: Path, name: str, branch: str) -> None:
        assert (source, target, name, branch) == (
            repos.source,
            repos.target,
            archive.PUBLIC_NAME,
            "main",
        )
        calls.append("validate")

    original_sync = archive.sync_history
    monkeypatch.setattr(archive, "validate_origins", validate)

    def checked_sync(
        source: Path, target: Path, name: str, branch: str, *, attempts: int = 3
    ) -> archive.ArchiveResult:
        assert calls == ["validate"]
        assert attempts == 3  # noqa: PLR2004
        return original_sync(source, target, name, branch, attempts=attempts)

    monkeypatch.setattr(archive, "sync_history", checked_sync)
    assert (
        archive.main(
            [
                "--source-repo",
                str(repos.source),
                "--target-repo",
                str(repos.target),
                "--source-name",
                archive.PUBLIC_NAME,
                "--source-branch",
                "main",
                "--attempts",
                "3",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["source_sha"] == repos.source_root
    assert output["target_branch"] == "main"
    assert output["archive_sha"] == repos.tip()
    assert output["source_tree"] == ORIGINAL_GIT(
        repos.source, "rev-parse", "HEAD^{tree}"
    )
    assert output["status"] == "appended"


def test_git_timeout_and_errors_propagate(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    def timeout(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == archive.GIT_TIMEOUT
        assert kwargs["check"] is True
        raise subprocess.TimeoutExpired("git", archive.GIT_TIMEOUT)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        archive.git(tmp_path, "version")
