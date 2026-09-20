from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROOT_README = ROOT / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "docker-release.yml"
UNRAID_TEMPLATE = ROOT / "templates" / "ironsbot.xml"
ENV_EXAMPLE = ROOT / ".env.example"
DOCKER_README = ROOT / "docker" / "README.md"
DOCKERHUB_DESCRIPTION_WORKFLOW = (
    ROOT / ".github" / "workflows" / "dockerhub-description.yml"
)

CURRENT_ACTION_MAJORS = {
    "actions/checkout": 7,
    "actions/setup-python": 7,
    "actions/upload-artifact": 7,
    "docker/build-push-action": 7,
    "docker/login-action": 4,
    "docker/metadata-action": 6,
    "docker/setup-buildx-action": 4,
}
PIP_AUDIT_TIMEOUT_MINUTES = 10


def test_seer_password_deployment_docs_require_plaintext_input() -> None:
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")
    unraid_template = UNRAID_TEMPLATE.read_text(encoding="utf-8")

    assert "One plain-text password per player ID" in env_example
    assert "设置明文密码" in env_example
    assert "enter the plain-text password" in unraid_template
    assert "填写明文密码" in unraid_template
    assert "密码 MD5 环境变量" not in unraid_template


def test_docker_env_example_lists_all_deployment_credentials() -> None:
    docker_readme = DOCKER_README.read_text(encoding="utf-8")
    env_block = docker_readme.split("```env", 1)[1].split("```", 1)[0]

    for variable in (
        "APP_CONFIG_PATH",
        "ONEBOT_ACCESS_TOKEN",
        "QQ_OFFICIAL_APP_ID_EXAMPLE_BOT",
        "QQ_OFFICIAL_SECRET_EXAMPLE_BOT",
        "AI_KEY_DEEPSEEK",
        "SEER_PASSWORD_123456789",
        "SENDPIC_CNB_TOKEN",
        "GITHUB_WORKFLOW_TOKEN",
        "DOCKER_REGISTRY_USERNAME",
        "DOCKER_REGISTRY_TOKEN",
    ):
        assert f"{variable}=" in env_block


def test_root_and_docker_readmes_describe_the_same_unified_image() -> None:
    root_readme = ROOT_README.read_text(encoding="utf-8")
    docker_readme = DOCKER_README.read_text(encoding="utf-8")

    assert "正式发布的 Docker 镜像已经同时包含" in root_readme
    assert "Published Docker images include the QQ Official runtime" in docker_readme
    assert "标准 OneBot 镜像不携带该 SDK" not in root_readme
    assert "Build an official-bot image" not in docker_readme


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


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_dockerhub_description_is_optional_without_repository_secrets() -> None:
    workflow = yaml.safe_load(
        DOCKERHUB_DESCRIPTION_WORKFLOW.read_text(encoding="utf-8")
    )
    assert workflow["env"] == {
        "DOCKERHUB_USERNAME": "${{ secrets.DOCKERHUB_USERNAME }}",
        "DOCKERHUB_TOKEN": "${{ secrets.DOCKERHUB_TOKEN }}",
    }
    steps = workflow["jobs"]["dockerhub-description"]["steps"]
    skip = next(
        step
        for step in steps
        if step["name"] == "Skip unavailable Docker Hub publication"
    )
    publish = next(
        step for step in steps if step["name"] == "Update Docker Hub Description"
    )
    assert skip["if"] == (
        "${{ env.DOCKERHUB_USERNAME == '' || env.DOCKERHUB_TOKEN == '' }}"
    )
    assert publish["if"] == (
        "${{ env.DOCKERHUB_USERNAME != '' && env.DOCKERHUB_TOKEN != '' }}"
    )
    assert publish["with"]["username"] == "${{ env.DOCKERHUB_USERNAME }}"
    assert publish["with"]["password"] == "${{ env.DOCKERHUB_TOKEN }}"


def test_workflows_use_current_first_party_action_contracts() -> None:
    uses_pattern = re.compile(r"uses:\s+([^\s@]+)@v(\d+)\s*$")
    observed: set[str] = set()

    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            match = uses_pattern.search(line)
            if match is None:
                continue
            action, raw_major = match.groups()
            expected = CURRENT_ACTION_MAJORS.get(action)
            if expected is None:
                continue
            observed.add(action)
            assert int(raw_major) == expected, (
                f"{workflow.name}: {action}@v{raw_major} must use v{expected}"
            )

    assert observed == set(CURRENT_ACTION_MAJORS)


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


def _run_candidate_budget(
    tmp_path: Path,
    *,
    app_kib: int,
    site_packages_kib: int,
    fonts_kib: int,
) -> subprocess.CompletedProcess:
    step = next(
        step
        for step in _steps()
        if step["name"] == "Enforce runtime candidate size budgets"
    )
    script = tmp_path / "candidate-budget.sh"
    script.write_text(
        """docker() {
    printf '%s\t/app\n' "$BUDGET_TEST_APP_KIB"
    printf '%s\t/usr/local/lib/python3.11/site-packages\n' \
        "$BUDGET_TEST_SITE_PACKAGES_KIB"
    printf '%s\t/usr/share/fonts\n' "$BUDGET_TEST_FONTS_KIB"
}
"""
        + step["run"],
        encoding="utf-8",
    )
    return subprocess.run(
        [_bash(), "--noprofile", "--norc", "-e", "-o", "pipefail", script.name],
        cwd=tmp_path,
        env={
            **os.environ,
            "RUNNER_TEMP": ".",
            "GITHUB_SHA": "a" * 40,
            "MAX_APP_KIB": str(step["env"]["MAX_APP_KIB"]),
            "MAX_SITE_PACKAGES_KIB": str(step["env"]["MAX_SITE_PACKAGES_KIB"]),
            "MAX_FONTS_KIB": str(step["env"]["MAX_FONTS_KIB"]),
            "BUDGET_TEST_APP_KIB": str(app_kib),
            "BUDGET_TEST_SITE_PACKAGES_KIB": str(site_packages_kib),
            "BUDGET_TEST_FONTS_KIB": str(fonts_kib),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=20,
    )


def _run_candidate_growth_gate(
    tmp_path: Path,
    *,
    candidate_bytes: int,
    baseline_bytes: int,
    baseline_available: bool = True,
) -> subprocess.CompletedProcess:
    step = next(
        step
        for step in _steps()
        if step["name"] == "Compare runtime candidate image growth"
    )
    script = tmp_path / "candidate-growth.sh"
    script.write_text(
        r"""docker() {
    case "$*" in
        image\ inspect\ ironsbot-ci:*--format*Size*)
            printf '%s\n' "$GROWTH_TEST_CANDIDATE_BYTES" ;;
        image\ inspect\ "$baseline_image"*RepoDigests*)
            printf '%s@sha256:%064d\n' "$baseline_image" 0 ;;
        image\ inspect\ "$baseline_image"*Size*)
            printf '%s\n' "$GROWTH_TEST_BASELINE_BYTES" ;;
        pull\ "$baseline_image")
            [ "$GROWTH_TEST_BASELINE_AVAILABLE" = "true" ] ;;
        *)
            printf 'unexpected docker call: %s\n' "$*" >&2
            return 2 ;;
    esac
}
"""
        + step["run"],
        encoding="utf-8",
    )
    return subprocess.run(
        [_bash(), "--noprofile", "--norc", "-e", "-o", "pipefail", script.name],
        cwd=tmp_path,
        env={
            **os.environ,
            "RUNNER_TEMP": ".",
            "GITHUB_SHA": "a" * 40,
            "BASELINE_IMAGE": str(step["env"]["BASELINE_IMAGE"]),
            "MAX_IMAGE_GROWTH_KIB": str(step["env"]["MAX_IMAGE_GROWTH_KIB"]),
            "GROWTH_TEST_CANDIDATE_BYTES": str(candidate_bytes),
            "GROWTH_TEST_BASELINE_BYTES": str(baseline_bytes),
            "GROWTH_TEST_BASELINE_AVAILABLE": str(baseline_available).lower(),
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
    assert "Docker-reported image size" in summary
    assert "uncompressed" not in summary


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
    expected_project_url = (
        "IRONSBOT_PROJECT_URL=${{ github.server_url }}/${{ github.repository }}"
    )
    assert expected_project_url in candidate["with"]["build-args"]
    assert expected_project_url in publish["with"]["build-args"]
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
    assert "find_spec" in smoke["run"]
    assert "pygments" in smoke["run"]
    assert "pymdownx" in smoke["run"]
    assert "template_to_pic" in smoke["run"]
    assert "89504e470d0a1a0a" in smoke["run"]
    assert '-e EXPECTED_PYTHON_VERSION="$PYTHON_VERSION"' in smoke["run"]
    assert "sys.version_info.major, sys.version_info.minor" in smoke["run"]
    assert '"$EXPECTED_PYTHON_VERSION"' in smoke["run"]
    assert "load_settings()" in smoke["run"]
    assert "import nonebot, qqbot_agent_sdk, seerapi_models" in smoke["run"]
    assert "QQOfficialRuntime" in smoke["run"]


def test_candidate_size_gate_precedes_registry_login_and_keeps_evidence() -> None:
    steps = _steps()
    smoke = next(
        step for step in steps if step["name"] == "Smoke test runtime candidate"
    )
    budget = next(
        step
        for step in steps
        if step["name"] == "Enforce runtime candidate size budgets"
    )
    upload = next(
        step for step in steps if step["name"] == "Upload candidate size evidence"
    )
    login = next(
        step for step in steps if step["name"] == "Login to GitHub Container Registry"
    )

    assert (
        steps.index(smoke)
        < steps.index(budget)
        < steps.index(upload)
        < steps.index(login)
    )
    assert upload["if"] == "${{ always() }}"
    assert upload["with"]["if-no-files-found"] == "warn"
    assert "--network none --entrypoint sh" in budget["run"]
    assert "ironsbot-candidate-runtime-size-kib.txt" in budget["run"]
    assert budget["env"]["MAX_SITE_PACKAGES_KIB"] == "122880"


def test_candidate_growth_gate_precedes_publish_and_keeps_evidence() -> None:
    steps = _steps()
    dockerhub_login = next(
        step for step in steps if step["name"] == "Login to Docker Hub"
    )
    growth = next(
        step
        for step in steps
        if step["name"] == "Compare runtime candidate image growth"
    )
    upload = next(
        step
        for step in steps
        if step["name"] == "Upload candidate image growth evidence"
    )
    publish = next(step for step in steps if step["name"] == "Build and Publish")

    assert steps.index(dockerhub_login) < steps.index(growth) < steps.index(upload)
    assert steps.index(upload) < steps.index(publish)
    assert growth["env"]["MAX_IMAGE_GROWTH_KIB"] == "20480"
    assert growth["env"]["BASELINE_IMAGE"] == (
        "ghcr.io/${{ github.repository }}:latest"
    )
    assert growth["env"]["FALLBACK_BASELINE_IMAGE"] == (
        "ghcr.io/${{ github.repository_owner }}/ironsbot:latest"
    )
    assert 'baseline_image="${BASELINE_IMAGE,,}"' in growth["run"]
    assert 'fallback_baseline_image="${FALLBACK_BASELINE_IMAGE,,}"' in growth["run"]
    assert 'docker pull "$baseline_image"' in growth["run"]
    assert 'echo "fallback_baseline=$baseline_image"' in growth["run"]
    assert 'docker image inspect "$candidate"' in growth["run"]
    assert upload["if"] == "${{ always() }}"
    assert upload["with"]["if-no-files-found"] == "warn"


def test_ghcr_image_repository_is_fork_aware() -> None:
    metadata = next(step for step in _steps() if step["name"] == "Generate Tags")

    assert "ghcr.io/${{ github.repository }}" in metadata["with"]["images"]
    assert (
        "ghcr.io/murmansk5000/ironsbot"
        not in WORKFLOW.read_text(encoding="utf-8").lower()
    )


@pytest.mark.parametrize(
    ("growth_kib", "expected_ok"),
    [
        (-1024, True),
        (0, True),
        (20480, True),
        (20481, False),
    ],
)
def test_candidate_image_growth_shell(
    tmp_path: Path,
    growth_kib: int,
    *,
    expected_ok: bool,
) -> None:
    baseline_bytes = 256 * 1024 * 1024
    result = _run_candidate_growth_gate(
        tmp_path,
        candidate_bytes=baseline_bytes + growth_kib * 1024,
        baseline_bytes=baseline_bytes,
    )

    assert (result.returncode == 0) is expected_ok, result.stdout + result.stderr
    evidence = (tmp_path / "ironsbot-candidate-image-growth.txt").read_text(
        encoding="utf-8"
    )
    assert f"growth_bytes={growth_kib * 1024}" in evidence
    assert "baseline_digest=" in evidence


def test_candidate_image_growth_requires_readable_baseline(tmp_path: Path) -> None:
    result = _run_candidate_growth_gate(
        tmp_path,
        candidate_bytes=256 * 1024 * 1024,
        baseline_bytes=0,
        baseline_available=False,
    )

    assert result.returncode != 0
    evidence = (tmp_path / "ironsbot-candidate-image-growth.txt").read_text(
        encoding="utf-8"
    )
    assert "candidate_bytes=" in evidence
    assert "baseline_digest=" not in evidence


@pytest.mark.parametrize(
    ("app_kib", "site_packages_kib", "fonts_kib", "expected_ok"),
    [
        (8192, 122880, 24576, True),
        (8193, 1, 1, False),
        (1, 122881, 1, False),
        (1, 1, 24577, False),
    ],
)
def test_candidate_size_budget_shell(
    tmp_path: Path,
    app_kib: int,
    site_packages_kib: int,
    fonts_kib: int,
    *,
    expected_ok: bool,
) -> None:
    result = _run_candidate_budget(
        tmp_path,
        app_kib=app_kib,
        site_packages_kib=site_packages_kib,
        fonts_kib=fonts_kib,
    )

    assert (result.returncode == 0) is expected_ok, result.stdout + result.stderr
    inventory = tmp_path / "ironsbot-candidate-runtime-size-kib.txt"
    assert inventory.is_file()


def test_runtime_uses_two_weight_cn_subset_fonts() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert 'ARG IRONSBOT_PROJECT_URL=""' in dockerfile
    assert "ENV IRONSBOT_PROJECT_URL=${IRONSBOT_PROJECT_URL}" in dockerfile
    assert "19_SourceHanSansCN.zip" in dockerfile
    assert "09_SourceHanSansSC.zip" not in dockerfile
    assert '"SourceHanSansCN-Regular.otf"' in dockerfile
    assert '"SourceHanSansCN-Bold.otf"' in dockerfile
    assert 'Path(name).name == "LICENSE.txt"' in dockerfile
    assert "/usr/share/doc/source-han-sans/LICENSE.txt" in dockerfile


def test_builder_and_runtime_pin_the_same_debian_release() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    from_lines = [
        line.strip() for line in dockerfile.splitlines() if line.startswith("FROM ")
    ]

    assert "ARG PYTHON_VERSION=3.11" in dockerfile
    assert from_lines == [
        "FROM python:${PYTHON_VERSION}-bookworm AS requirements_stage",
        "FROM python:${PYTHON_VERSION}-slim-bookworm",
    ]


def test_runtime_python_baseline_is_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    workflow = _workflow()
    expected = workflow["env"]["PYTHON_VERSION"]
    setup = next(step for step in _steps() if step["name"] == "Setup Python")
    audit = next(
        step for step in _steps() if step["name"] == "Audit locked runtime dependencies"
    )
    candidate = next(
        step for step in _steps() if step["name"] == "Build runtime candidate"
    )
    publish = next(step for step in _steps() if step["name"] == "Build and Publish")

    assert expected == "3.11"
    assert project["project"]["requires-python"] == f">={expected}, <4.0"
    assert project["tool"]["basedpyright"]["pythonVersion"] == expected
    assert not any(
        dependency.startswith("tomli")
        for dependency in project["project"]["dependencies"]
    )
    assert setup["with"]["python-version"] == "${{ env.PYTHON_VERSION }}"
    assert '--python "$PYTHON_VERSION" --from pip-audit==2.10.1' in audit["run"]
    assert audit["timeout-minutes"] == PIP_AUDIT_TIMEOUT_MINUTES
    assert "--progress-spinner off --timeout 30" in audit["run"]
    version_argument = "PYTHON_VERSION=${{ env.PYTHON_VERSION }}"
    extra_argument = "IRONSBOT_RUNTIME_EXTRA=${{ env.IRONSBOT_RUNTIME_EXTRA }}"
    assert version_argument in candidate["with"]["build-args"]
    assert version_argument in publish["with"]["build-args"]
    assert extra_argument in candidate["with"]["build-args"]
    assert extra_argument in publish["with"]["build-args"]
    assert 'extra_args=(--extra "$IRONSBOT_RUNTIME_EXTRA")' in audit["run"]
    assert workflow["env"]["IRONSBOT_RUNTIME_EXTRA"] == "qq-official"


def test_runtime_audit_precedes_credentials_and_keeps_failure_evidence() -> None:
    steps = _steps()
    audit = next(s for s in steps if s["name"] == "Audit locked runtime dependencies")
    upload = next(s for s in steps if s["name"] == "Upload dependency audit evidence")
    login = next(s for s in steps if s["name"] == "Login to GitHub Container Registry")
    assert steps.index(audit) < steps.index(upload) < steps.index(login)
    assert "--frozen --no-dev --no-emit-project" in audit["run"]
    assert '--python "$PYTHON_VERSION" --from pip-audit==2.10.1' in audit["run"]
    assert "--require-hashes --disable-pip --strict" in audit["run"]
    assert audit["timeout-minutes"] == PIP_AUDIT_TIMEOUT_MINUTES
    assert "--progress-spinner off --timeout 30" in audit["run"]
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
