from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "docker-release.yml"


def _bash() -> str:
    if os.name == "nt" and (git := shutil.which("git")):
        git_bash = Path(git).resolve().parents[1] / "bin" / "bash.exe"
        if git_bash.is_file():
            return str(git_bash)
    if executable := shutil.which("bash"):
        return executable
    pytest.skip("workflow shell tests require Bash")


def _steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["docker"][
        "steps"
    ]


def _run_measurement(
    tmp_path: Path, tags: str, digest: str
) -> subprocess.CompletedProcess:
    step = next(
        step for step in _steps() if step["name"] == "Record published image size"
    )
    script = tmp_path / "measure.sh"
    script.write_text(
        """docker() {
    printf '%s\\n' "$*" >> docker-calls.txt
    case "$*" in
        *--format*Size*) printf '1048576\\n' ;;
        'image inspect '*) printf '[]\\n' ;;
        'image history '*) printf '{}\\n' ;;
        'run --rm --network none --entrypoint sh '*) printf '1024\\t/app\\n' ;;
    esac
}
python() { "$WORKFLOW_TEST_PYTHON" "$@"; }
"""
        + step["run"],
        encoding="utf-8",
    )
    return subprocess.run(
        [_bash(), "--noprofile", "--norc", "-e", "-o", "pipefail", script.name],
        cwd=tmp_path,
        env={
            **os.environ,
            "IMAGE_TAGS": tags,
            "IMAGE_DIGEST": digest,
            "RUNNER_TEMP": ".",
            "GITHUB_STEP_SUMMARY": "summary.md",
            "WORKFLOW_TEST_PYTHON": sys.executable,
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=20,
    )


@pytest.mark.parametrize(
    "repository", ["ghcr.io/example/bot", "localhost:5000/example/bot"]
)
def test_size_measurement_uses_digest_and_keeps_layer_evidence(
    tmp_path: Path, repository: str
) -> None:
    digest = "sha256:" + "a" * 64
    result = _run_measurement(
        tmp_path, f"{repository}:latest\n{repository}:test", digest
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "docker-calls.txt").read_text(encoding="utf-8").splitlines()
    assert calls
    assert all(f"{repository}@{digest}" in call for call in calls)
    assert all(":latest" not in call and ":test" not in call for call in calls)
    assert (tmp_path / "ironsbot-image-inspect.json").is_file()
    assert (tmp_path / "ironsbot-image-history.jsonl").is_file()
    assert (
        tmp_path / "ironsbot-runtime-size-kib.txt"
    ).read_text().strip() == "1024\t/app"
    inventory = next(call for call in calls if call.startswith("run "))
    assert "--network none --entrypoint sh" in inventory
    assert (
        "du -k -d 1 /app /usr/local/lib/python*/site-packages /usr/share/fonts"
        in inventory
    )
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert f"{repository}@{digest}" in summary
    assert "1.0 MiB" in summary


def test_missing_digest_fails_without_pulling_a_mutable_tag(tmp_path: Path) -> None:
    result = _run_measurement(tmp_path, "example/bot:latest", "")
    assert result.returncode != 0
    assert "missing published image digest" in result.stderr
    assert not (tmp_path / "docker-calls.txt").exists()


def test_release_connects_measurement_to_build_digest_and_artifact() -> None:
    steps = _steps()
    build = next(step for step in steps if step["name"] == "Build and Publish")
    measure = next(
        step for step in steps if step["name"] == "Record published image size"
    )
    upload = next(
        step for step in steps if step["name"] == "Upload image size evidence"
    )
    assert build["id"] == "build"
    assert measure["env"]["IMAGE_DIGEST"] == "${{ steps.build.outputs.digest }}"
    assert "ironsbot-image-inspect.json" in upload["with"]["path"]
    assert "ironsbot-image-history.jsonl" in upload["with"]["path"]
    assert "ironsbot-runtime-size-kib.txt" in upload["with"]["path"]
    assert upload["with"]["if-no-files-found"] == "error"


def test_runtime_candidate_is_smoked_before_registry_login_and_publish() -> None:
    steps = _steps()
    candidate = next(
        step for step in steps if step["name"] == "Build runtime candidate"
    )
    smoke = next(
        step for step in steps if step["name"] == "Smoke test runtime candidate"
    )
    ghcr_login = next(
        step for step in steps if step["name"] == "Login to GitHub Container Registry"
    )
    dockerhub_login = next(
        step for step in steps if step["name"] == "Login to Docker Hub"
    )
    publish = next(step for step in steps if step["name"] == "Build and Publish")

    assert candidate["with"]["load"] is True
    assert candidate["with"]["push"] is False
    assert candidate["with"]["context"] == publish["with"]["context"] == "."
    assert candidate["with"]["labels"] == publish["with"]["labels"]
    assert steps.index(candidate) < steps.index(smoke)
    assert steps.index(smoke) < steps.index(ghcr_login) < steps.index(publish)
    assert steps.index(smoke) < steps.index(dockerhub_login) < steps.index(publish)
    assert "check_on_startup = false" in smoke["run"]
    assert "docker run --rm --network none" in smoke["run"]
    assert "$smoke_config:/config/ironsbot.toml:ro" in smoke["run"]
    assert "--entrypoint" not in smoke["run"]
    assert 'fc-match -f "%{file}" "Source Han Sans CN:style=Regular"' in smoke["run"]
    assert 'fc-match -f "%{file}" "Source Han Sans CN:style=Bold"' in smoke["run"]
    assert 'test "$regular" != "$bold"' in smoke["run"]
    assert "load_settings()" in smoke["run"]


def test_runtime_uses_two_weight_cn_subset_fonts() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "19_SourceHanSansCN.zip" in dockerfile
    assert "09_SourceHanSansSC.zip" not in dockerfile
    assert '"SourceHanSansCN-Regular.otf"' in dockerfile
    assert '"SourceHanSansCN-Bold.otf"' in dockerfile
    assert 'Path(name).name == "LICENSE.txt"' in dockerfile
    assert "/usr/share/doc/source-han-sans/LICENSE.txt" in dockerfile


def test_runtime_audit_precedes_credentials_and_keeps_failure_evidence() -> None:
    steps = _steps()
    audit = next(s for s in steps if s["name"] == "Audit locked runtime dependencies")
    upload = next(s for s in steps if s["name"] == "Upload dependency audit evidence")
    login = next(s for s in steps if s["name"] == "Login to GitHub Container Registry")
    assert steps.index(audit) < steps.index(upload) < steps.index(login)
    assert "--frozen --no-dev --no-emit-project" in audit["run"]
    assert "--python 3.10 --from pip-audit==2.10.1" in audit["run"]
    assert "--require-hashes --disable-pip --strict" in audit["run"]
    assert "--fix" not in audit["run"]
    assert "--ignore-vuln" not in audit["run"]
    assert not audit.get("continue-on-error", False)
    assert upload["if"] == "${{ always() }}"
    assert "ironsbot-dependency-audit.json" in upload["with"]["path"]
    assert "ironsbot-runtime-requirements.txt" in upload["with"]["path"]
    assert "pip-audit" not in (ROOT / "Dockerfile").read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", ["none", "export", "audit"])
def test_runtime_audit_shell_propagates_failure(tmp_path: Path, failure: str) -> None:
    step = next(s for s in _steps() if s["name"] == "Audit locked runtime dependencies")
    script = tmp_path / "audit.sh"
    script.write_text(
        """python() {
    printf '%s\\n' "$*" >> audit-calls.txt
    case "$*" in
        *'uv export '*)
            if [ "$AUDIT_TEST_FAILURE" = export ]; then return 2; fi
            printf 'h2==4.4.1\\n' > "$RUNNER_TEMP/ironsbot-runtime-requirements.txt"
            ;;
        *'uv tool run '*)
            printf '{}\\n' > "$RUNNER_TEMP/ironsbot-dependency-audit.json"
            if [ "$AUDIT_TEST_FAILURE" = audit ]; then return 1; fi
            ;;
        *) return 99 ;;
    esac
}
"""
        + step["run"],
        encoding="utf-8",
    )
    result = subprocess.run(
        [_bash(), "--noprofile", "--norc", "-e", "-o", "pipefail", script.name],
        cwd=tmp_path,
        env={**os.environ, "RUNNER_TEMP": ".", "AUDIT_TEST_FAILURE": failure},
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == {"none": 0, "export": 2, "audit": 1}[failure]
    calls = (tmp_path / "audit-calls.txt").read_text().splitlines()
    assert len(calls) == (1 if failure == "export" else 2)
    assert (tmp_path / "ironsbot-dependency-audit.json").exists() == (
        failure != "export"
    )
