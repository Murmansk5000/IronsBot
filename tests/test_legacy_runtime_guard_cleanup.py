from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.app import docker_preflight as startup
from ironsbot.config.models.operations import (
    DockerUpdateConfig,
    PrivateExtensionsConfig,
)
from ironsbot.integrations.docker import client as docker_module
from ironsbot.services.operations.docker_models import (
    DockerImageInfo,
    DockerUpdateRequest,
    DockerUpdateResult,
    WatchtowerUpdateOptions,
)
from ironsbot.services.operations.docker_preflight import (
    DockerStartupPreflightAction,
    DockerStartupPreflightService,
    DockerStartupPreflightStore,
    DockerUpdateRunner,
    _record_from_payload,
    consume_docker_startup_preflight_notice,
)

if TYPE_CHECKING:
    from pathlib import Path


def _old_record(*, blocked: bool = False) -> dict[str, object]:
    result = DockerUpdateResult(
        ok=not blocked,
        current_image_id="sha256:old",
        target_image_id="sha256:new",
        updater_container_id="" if blocked else "supervisor",
    )
    return {
        "container_name": "bot",
        "image": "public:latest",
        "result": asdict(result)
        | {
            "blocked_by_policy": blocked,
            "another_retired_result_field": "ignored",
        },
        "source_instance_id": "source",
        "handoff_completed": False,
        "created_at": 100.0,
    }


@pytest.mark.parametrize("blocked", [False, True])
def test_old_results_preserve_known_fields_without_retired_policy(
    *, blocked: bool
) -> None:
    record = _record_from_payload(_old_record(blocked=blocked))
    assert record.result.ok is not blocked
    assert record.result.current_image_id == "sha256:old"
    assert record.result.target_image_id == "sha256:new"
    assert record.result.updater_container_id == ("" if blocked else "supervisor")
    assert record.source_instance_id == "source"
    assert not hasattr(record.result, "blocked_by_policy")
    assert "blocked_by_policy" not in asdict(record.result)


def test_old_completed_handoff_notice_is_consumed_once(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"
    payload = _old_record()
    payload["handoff_completed"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = DockerStartupPreflightStore(path)
    notice = consume_docker_startup_preflight_notice(store)
    assert notice is not None and "new" in notice
    assert consume_docker_startup_preflight_notice(store) is None
    assert not path.exists()


@pytest.mark.asyncio
async def test_old_pending_handoff_is_verified_not_restarted(tmp_path: Path) -> None:
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(_old_record()), encoding="utf-8")
    runner = SimpleNamespace(
        run_update=AsyncMock(side_effect=AssertionError("unexpected second update")),
        confirm_update_handoff=AsyncMock(return_value=True),
        abandon_update_handoff=AsyncMock(),
    )
    store = DockerStartupPreflightStore(path)
    service = DockerStartupPreflightService(
        DockerUpdateConfig(check_on_startup=True, image="public:latest"),
        cast("DockerUpdateRunner", runner),
        store,
        instance_id="target",
    )
    assert await service.run() is DockerStartupPreflightAction.CONTINUE
    runner.confirm_update_handoff.assert_awaited_once_with(
        previous_image_id="sha256:old",
        expected_image_id="sha256:new",
        updater_container_id="supervisor",
    )
    runner.run_update.assert_not_awaited()
    runner.abandon_update_handoff.assert_not_awaited()
    record = store.read()
    assert record is not None and record.handoff_completed


@pytest.mark.asyncio
@pytest.mark.parametrize("source_instance", [False, True])
async def test_old_unverified_handoff_keeps_boot_blocked(
    tmp_path: Path, *, source_instance: bool
) -> None:
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(_old_record()), encoding="utf-8")
    runner = SimpleNamespace(
        run_update=AsyncMock(
            return_value=("bot", DockerUpdateResult(ok=False, message="offline"))
        ),
        confirm_update_handoff=AsyncMock(return_value=False),
        abandon_update_handoff=AsyncMock(),
    )
    store = DockerStartupPreflightStore(path)
    service = DockerStartupPreflightService(
        DockerUpdateConfig(
            check_on_startup=True,
            image="public:latest",
            fallback_to_current_image_on_handoff_failure=False,
        ),
        cast("DockerUpdateRunner", runner),
        store,
        instance_id="source" if source_instance else "target",
        now=lambda: 110.0,
    )
    assert await service.run() is DockerStartupPreflightAction.WAIT_FOR_WATCHTOWER
    runner.confirm_update_handoff.assert_awaited_once()
    runner.abandon_update_handoff.assert_not_awaited()
    if source_instance:
        runner.run_update.assert_not_awaited()
    else:
        runner.run_update.assert_awaited_once()
    record = store.read()
    assert record is not None and not record.handoff_completed
    assert record.result.target_image_id == "sha256:new"
    assert record.result.updater_container_id == "supervisor"


@pytest.mark.parametrize("case", ["missing-ok", "invalid-result", "invalid-created"])
def test_projection_does_not_accept_malformed_records(
    tmp_path: Path, case: str
) -> None:
    payload = _old_record()
    if case == "missing-ok":
        result = payload["result"]
        assert isinstance(result, dict)
        result.pop("ok")
    elif case == "invalid-result":
        payload["result"] = []
    else:
        payload["created_at"] = True
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert DockerStartupPreflightStore(path).read() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_extension_refresh_does_not_require_running_image_identity(
    monkeypatch: pytest.MonkeyPatch, *, enabled: bool
) -> None:
    # No identity API exists on this synthetic gateway.
    gateway = object()
    factory = Mock(return_value=gateway)
    install = AsyncMock()
    installer = Mock(return_value=SimpleNamespace(install=install))
    monkeypatch.setattr(startup, "DockerClient", factory)
    monkeypatch.setattr(startup, "PrivateExtensionInstaller", installer)
    config = PrivateExtensionsConfig(enabled=enabled)
    docker_config = DockerUpdateConfig()
    await startup.run_private_extensions_preflight(config, docker_config)
    if enabled:
        installer.assert_called_once_with(config, docker_config, gateway)
        install.assert_awaited_once_with()
    else:
        factory.assert_not_called()
        installer.assert_not_called()
        install.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("check_only", [False, True])
@pytest.mark.parametrize("legacy_label", [False, True])
async def test_ordinary_updates_ignore_retired_private_runtime_label(
    monkeypatch: pytest.MonkeyPatch, *, check_only: bool, legacy_label: bool
) -> None:
    current = DockerImageInfo(
        "sha256:old",
        labels={"io.ironsbot.private-runtime.revision": "a" * 40}
        if legacy_label
        else {},
        repo_digests=("public@sha256:old",),
    )
    target = DockerImageInfo("sha256:new")
    gateway = docker_module.DockerClient()
    monkeypatch.setattr(gateway, "socket_exists", AsyncMock(return_value=True))
    context = Mock()
    context.__aenter__ = AsyncMock(return_value=object())
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(docker_module.httpx, "AsyncClient", Mock(return_value=context))
    calls = {
        "inspect_container_image_id": AsyncMock(return_value=current.image_id),
        "inspect_image_info": AsyncMock(return_value=current),
        "pull_docker_image": AsyncMock(return_value=target),
        "inspect_remote_image_digest": AsyncMock(return_value="sha256:new"),
        "inspect_remote_image_info": AsyncMock(return_value=target),
        "resolve_image_commit_summary": AsyncMock(return_value=""),
        "remove_stopped_watchtower_containers": AsyncMock(return_value=0),
        "launch_supervisor": AsyncMock(return_value="supervisor"),
    }
    for name, call in calls.items():
        monkeypatch.setattr(docker_module, name, call)
    request = DockerUpdateRequest(
        "bot",
        "public:latest",
        "/fictional.sock",
        WatchtowerUpdateOptions("watchtower", "1.40"),
        1.0,
    )
    if check_only:
        result = await gateway.check_update(request)
        assert result.ok and not result.up_to_date
        calls["inspect_remote_image_digest"].assert_awaited_once()
        calls["inspect_remote_image_info"].assert_awaited_once()
        calls["pull_docker_image"].assert_not_awaited()
        calls["launch_supervisor"].assert_not_awaited()
        calls["remove_stopped_watchtower_containers"].assert_not_awaited()
    else:
        updated = await gateway.start_update(request)
        assert updated.ok and updated.updater_container_id == "supervisor"
        calls["pull_docker_image"].assert_awaited_once()
        calls["launch_supervisor"].assert_awaited_once()
        calls["inspect_remote_image_digest"].assert_not_awaited()
