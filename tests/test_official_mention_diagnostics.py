from __future__ import annotations

import asyncio
import json
import os
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import AsyncClient

from ironsbot.core.platform import reference_digest
from ironsbot.integrations.qq_official.mention_diagnostics import (
    MAX_BYTES,
    MAX_EVENTS,
    MAX_SECONDS,
    MentionDiagnosticError,
    QQMentionDiagnostics,
    diagnostics_from_settings,
)
from ironsbot.integrations.qq_official.runtime import (
    QQOfficialRuntime,
    QQOfficialRuntimeAccount,
)

if TYPE_CHECKING:
    from pathlib import Path

APP = "example-app"
GROUP = "opaque-group"
NOW = 1_800_000_000.0
ENUM_EXAMPLE = 7
PRIVATE_MODE = 0o600


def _capture(tmp_path: Path, clock: Any = None) -> QQMentionDiagnostics:
    return QQMentionDiagnostics(
        tmp_path / "diagnostics",
        trusted_targets=frozenset({(APP, GROUP), ("other-app", "other-group")}),
        clock=clock or (lambda: NOW),
    )


def _raw(index: int = 1) -> dict[str, Any]:
    return {
        "id": f"private-message-{index}",
        "group_openid": GROUP,
        "content": "private-body @全体成员 <@&all> <@!private-member>",
        "author": {"member_openid": "private-member", "username": "private-nickname"},
        "at_all": True,
        "mentions": [
            {"type": "all", "id": "all"},
            {"is_you": True, "member_openid": "private-bot"},
        ],
        "attachments": [
            {
                "content_type": "image/png",
                "url": "https://private.invalid/signed?token=secret",
                "filename": "private-image-name",
            }
        ],
        "authorization": "private-authorization",
        "token": "private-token",
        "unknown_metadata": {
            "type": 7,
            "mention_type": "AT_ALL",
            "member_openid": "private-extra-member",
        },
    }


@pytest.mark.asyncio
async def test_diagnostics_are_disabled_until_explicitly_enabled(
    tmp_path: Path,
) -> None:
    diagnostics = _capture(tmp_path)
    await diagnostics.observe(APP, "GROUP_AT_MESSAGE_CREATE", _raw())
    assert not diagnostics.directory.exists()
    assert diagnostics.status() == {"active": False, "count": 0}


@pytest.mark.asyncio
async def test_only_exact_account_and_trusted_group_are_recorded_privately(
    tmp_path: Path,
) -> None:
    diagnostics = _capture(tmp_path)
    diagnostics.enable(APP, GROUP)
    for app, event, raw in [
        ("other-app", "GROUP_AT_MESSAGE_CREATE", _raw()),
        (APP, "GROUP_AT_MESSAGE_CREATE", {**_raw(), "group_openid": "other-group"}),
        (
            "other-app",
            "GROUP_AT_MESSAGE_CREATE",
            {**_raw(), "group_openid": "other-group"},
        ),
        (APP, "C2C_MESSAGE_CREATE", _raw()),
    ]:
        await diagnostics.observe(app, event, raw)
    assert diagnostics.status()["count"] == 0
    await diagnostics.observe(APP, "GROUP_AT_MESSAGE_CREATE", _raw())
    state = diagnostics.status()
    assert state["count"] == 1 and state["active"]
    record = state["records"][0]
    assert record["message_ref"] == reference_digest("private-message-1")
    fields = record["shape"]["fields"]
    assert fields["at_all"]["value"] is True
    assert fields["mentions"]["items"][0]["fields"]["type"]["value"] == "all"
    assert fields["unknown_metadata"]["fields"]["type"]["value"] == ENUM_EXAMPLE
    assert fields["unknown_metadata"]["fields"]["mention_type"]["value"] == "AT_ALL"
    assert fields["content"]["mention_markup"] == [
        {"modifier": "&", "target_kind": "all"},
        {"modifier": "!", "target_kind": "opaque"},
    ]
    stored = diagnostics.control.read_text()
    for value in (
        GROUP,
        "private-body",
        "@全体成员",
        "private-member",
        "private-nickname",
        "private-bot",
        "https://",
        "private-authorization",
        "private-token",
        "private-image-name",
        "private-extra-member",
        "private-message-1",
    ):
        assert value not in stored
    assert diagnostics.control.stat().st_size < MAX_BYTES
    if os.name != "nt":
        assert diagnostics.control.stat().st_mode & 0o777 == PRIVATE_MODE
    assert not list(diagnostics.directory.glob("*.tmp"))
    assert not (diagnostics.directory / "control.lock").exists()


@pytest.mark.asyncio
async def test_mention_scope_keeps_only_controlled_enum_values(tmp_path: Path) -> None:
    diagnostics = _capture(tmp_path)
    diagnostics.enable(APP, GROUP)
    raw = _raw()
    raw["mentions"] = [
        {"scope": "all", "is_you": True},
        {"scope": "user", "is_you": False},
        {"scope": "private-scope-value", "is_you": False},
    ]
    await diagnostics.observe(APP, "GROUP_MESSAGE_CREATE", raw)
    fields = diagnostics.status()["records"][0]["shape"]["fields"]
    mentions = fields["mentions"]["items"]
    assert mentions[0]["fields"]["scope"]["value"] == "all"
    assert mentions[1]["fields"]["scope"]["value"] == "user"
    assert "value" not in mentions[2]["fields"]["scope"]
    assert "private-scope-value" not in diagnostics.control.read_text()


@pytest.mark.asyncio
async def test_budget_persists_across_restarts_and_duplicate_events(
    tmp_path: Path,
) -> None:
    diagnostics = _capture(tmp_path)
    original = diagnostics.enable(APP, GROUP)
    await diagnostics.observe(APP, "GROUP_AT_MESSAGE_CREATE", _raw())
    await diagnostics.observe(APP, "GROUP_AT_MESSAGE_CREATE", _raw())
    assert diagnostics.status()["count"] == 1
    restarted = _capture(tmp_path)
    for index in range(2, MAX_EVENTS + 5):
        await restarted.observe(APP, "GROUP_AT_MESSAGE_CREATE", _raw(index))
    state = restarted.status()
    assert state["count"] == MAX_EVENTS and not state["active"]
    assert state["expires_at"] == original["expires_at"]
    with pytest.raises(MentionDiagnosticError, match="session_exists"):
        restarted.enable(APP, GROUP)


@pytest.mark.asyncio
async def test_distinct_event_types_for_same_message_keep_both_shapes(
    tmp_path: Path,
) -> None:
    diagnostics = _capture(tmp_path)
    diagnostics.enable(APP, GROUP)
    types = ("GROUP_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE")
    await asyncio.gather(*(diagnostics.observe(APP, event, _raw()) for event in types))
    records = diagnostics.status()["records"]
    assert len(records) == len(types)
    assert {record["event_type"] for record in records} == set(types)


@pytest.mark.asyncio
async def test_expiry_reads_and_disable_do_not_renew_window(tmp_path: Path) -> None:
    clock = [NOW]
    diagnostics = _capture(tmp_path, lambda: clock[0])
    original = diagnostics.enable(APP, GROUP)
    clock[0] += MAX_SECONDS - 1
    await diagnostics.observe(APP, "GROUP_MESSAGE_CREATE", _raw())
    assert diagnostics.status()["active"]
    clock[0] += 1
    await diagnostics.observe(APP, "GROUP_MESSAGE_CREATE", _raw(2))
    assert not diagnostics.status()["active"] and diagnostics.status()["count"] == 1
    assert diagnostics.status()["expires_at"] == original["expires_at"]
    diagnostics.disable()
    assert not diagnostics.status()["enabled"]
    diagnostics.disable(clear=True)
    assert not diagnostics.control.exists()
    diagnostics.disable(clear=True)


@pytest.mark.asyncio
async def test_concurrent_instances_never_exceed_persistent_cap(tmp_path: Path) -> None:
    first, second = _capture(tmp_path), _capture(tmp_path)
    first.enable(APP, GROUP)
    await asyncio.gather(
        *(
            instance.observe(APP, "GROUP_MESSAGE_CREATE", _raw(index))
            for index, instance in enumerate([first, second] * MAX_EVENTS)
        )
    )
    assert 0 < first.status()["count"] <= MAX_EVENTS
    assert first.status()["count"] == second.status()["count"]


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["json", "oversize", "records", "ttl"])
async def test_corrupt_control_fails_closed_without_event_logging(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, damage: str
) -> None:
    diagnostics = _capture(tmp_path)
    diagnostics.enable(APP, GROUP)
    state = json.loads(diagnostics.control.read_text())
    if damage == "records":
        state["records"] = ["private-body"]
    if damage == "ttl":
        state["expires_at"] = NOW + MAX_SECONDS + 1
    diagnostics.control.write_text(
        "private-body"
        if damage == "json"
        else "x" * (MAX_BYTES + 1)
        if damage == "oversize"
        else json.dumps(state)
    )
    await diagnostics.observe(APP, "GROUP_AT_MESSAGE_CREATE", _raw())
    await diagnostics.observe(APP, "GROUP_AT_MESSAGE_CREATE", _raw())
    assert "private-body" not in caplog.text and "private-token" not in caplog.text
    assert caplog.text.count("QQ mention diagnostics unavailable") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [OSError("private-body"), RuntimeError("private-body")]
)
async def test_write_failure_is_nonfatal_and_payload_shape_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    diagnostics = _capture(tmp_path)
    diagnostics.enable(APP, GROUP)
    raw = _raw()
    raw["nested"] = [[{"data": ["private-body"] * 100}] * 100] * 100
    await diagnostics.observe(APP, "GROUP_MESSAGE_CREATE", raw)
    assert diagnostics.status()["count"] == 1
    monkeypatch.setattr(diagnostics, "_write", Mock(side_effect=failure))
    await diagnostics.observe(APP, "GROUP_MESSAGE_CREATE", _raw(2))
    assert diagnostics.status()["count"] == 1


def test_operator_cannot_enable_untrusted_targets(tmp_path: Path) -> None:
    with pytest.raises(MentionDiagnosticError, match="untrusted_target"):
        _capture(tmp_path).enable(APP, "untrusted-group")
    assert not (tmp_path / "diagnostics").exists()


@pytest.mark.asyncio
async def test_runtime_records_before_parser_without_changing_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ironsbot.integrations.qq_official import runtime as module

    diagnostics = _capture(tmp_path)
    diagnostics.enable(APP, GROUP)
    raw = _raw()
    parsed = []

    def parse(event_type: str, payload: Any) -> None:
        assert diagnostics.status()["count"] == 1
        parsed.append((event_type, payload))

    monkeypatch.setattr(module, "parse_message_event", parse)
    async with AsyncClient() as client:
        runtime = QQOfficialRuntime(
            (QQOfficialRuntimeAccount(APP, "fictional-secret"),),
            http_client=client,
            session_root=tmp_path / "sessions",
            mention_diagnostics=diagnostics,
        )
        await runtime.handle_event(APP, "GROUP_AT_MESSAGE_CREATE", raw)
    assert parsed == [("GROUP_AT_MESSAGE_CREATE", raw)]


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", [False, True])
async def test_runtime_forwards_same_context_even_if_diagnostics_fail(
    tmp_path: Path, *, corrupt: bool
) -> None:
    diagnostics = _capture(tmp_path)
    diagnostics.enable(APP, GROUP)
    if corrupt:
        diagnostics.control.write_text("broken-private-body")
    raw = _raw()
    raw.pop("at_all")
    raw["mentions"] = [{"is_you": True}]
    handle = AsyncMock(return_value=True)
    async with AsyncClient() as client:
        runtime = QQOfficialRuntime(
            (QQOfficialRuntimeAccount(APP, "fictional-secret"),),
            http_client=client,
            session_root=tmp_path / "sessions",
            mention_diagnostics=diagnostics,
        )
        runtime.bind(
            cast("Any", SimpleNamespace(ingress=SimpleNamespace(handle=handle))),
            cast("Any", Mock()),
        )
        await runtime.handle_event(APP, "GROUP_AT_MESSAGE_CREATE", raw)
    handle.assert_awaited_once()
    observed = handle.await_args
    assert observed is not None
    context = observed.args[0]
    assert context.mentions_bot and not context.mentions_everyone
    assert "@全体成员" in context.text


def test_factory_uses_only_enabled_account_scoped_configured_endpoints(
    tmp_path: Path,
) -> None:
    settings = SimpleNamespace(
        paths=SimpleNamespace(runtime_state=tmp_path / "state.sqlite"),
        bot=SimpleNamespace(
            qq_official=SimpleNamespace(
                enabled_accounts={"test": SimpleNamespace(app_id=APP)}
            )
        ),
        identities=SimpleNamespace(
            groups={
                "room": SimpleNamespace(
                    official={"test": GROUP, "disabled": "foreign-openid"}
                )
            }
        ),
    )
    diagnostics = diagnostics_from_settings(cast("Any", settings))
    assert diagnostics.trusted_targets == frozenset({(APP, GROUP)})
    assert diagnostics.directory == tmp_path / "mention_diagnostics"
