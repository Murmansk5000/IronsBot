from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.seer import SeerConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.outbound import OutboundMessage, SendResult
from ironsbot.core.platform import Platform
from ironsbot.integrations.storage.player_bindings import SqlitePlayerBindingStore
from ironsbot.services.operations.request_feedback import send_request_feedback
from ironsbot.services.player_binding_confirmation import binding_query_reply
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import PortableReply, deliver_portable_reply
from ironsbot.services.seer.player_binding import PlayerBindingError
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionRegistry,
)
from ironsbot.services.seer.player_service import PlayerQueryResult, PlayerService
from ironsbot.services.seer.query_result import QueryReply
from tests.test_portable_player_commands import (
    _after_binding_receipt,
    _context,
    _pending,
    _resolver,
    _text,
)

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 11, 20, 10, 3, tzinfo=timezone.utc)
PLAYER = 700001
OTHER_PLAYER = 600002


def runtime(
    tmp_path: Path, platform: Platform, *, command: str = "绑定米米号700001"
) -> SimpleNamespace:
    context = _context(command, platform=platform)
    clock = SimpleNamespace(value=0.0, date=NOW)
    store = SqlitePlayerBindingStore(tmp_path / "bindings.sqlite")
    service = PlayerService(
        config=SeerConfig(),
        bindings=store,
        headless=cast("Any", None),
        error_message=cast("Any", None),
        details=cast("Any", None),
        now=lambda: clock.date,
    )
    pending = _pending(PLAYER)
    service.query = AsyncMock(return_value=PlayerQueryResult(pending=pending))
    service.start_background_refresh = Mock()
    service.record_returned_query = Mock(wraps=service.record_returned_query)
    policy = {context.message.conversation: frozenset({"seer_player"})}
    features = FeatureService(policy, {}, frozenset())
    sessions = PortableQuerySessions(ttl_seconds=5, now=lambda: clock.value)
    operations = build_portable_player_operations(
        service, _resolver(), sessions, features, PlayerDetailExtensionRegistry()
    )
    return SimpleNamespace(
        context=context,
        clock=clock,
        store=store,
        service=service,
        pending=pending,
        policy=policy,
        sessions=sessions,
        operations=operations,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("existing", [False, True])
async def test_explicit_binding_confirms_then_shows_only_one_prepared_profile(
    tmp_path: Path, platform: Platform, *, existing: bool
) -> None:
    app = runtime(tmp_path, platform)
    actor = app.context.message.actor
    if existing:
        app.store.bind(
            actor=actor,
            player_id=600001,
            player_nick="old",
            changed_at=NOW - timedelta(days=4),
        )
    opened = await app.operations["seer.player.bind"](app.context.text, app.context)
    assert isinstance(opened, PortableReply)
    text = _text(opened)
    assert text == app.service.shortcut_binding_offer(PLAYER, actor=actor)
    assert "换绑冷却为【3】个北京时间自然日。" in text
    assert "回复 是/y 绑定，否/n 不绑定，0 退出。" in text
    assert app.store.get(actor).player_id == (600001 if existing else None)
    app.service.record_returned_query.assert_not_called()
    result = await app.sessions.select("y", app.context, allow_deferred=True)
    assert isinstance(result, PortableReply)
    assert "已设置默认米米号：700001" in _text(result)
    assert "2026-11-23 00:00" in _text(result)
    app.service.record_returned_query.assert_not_called()
    result = await _after_binding_receipt(result)
    assert "player:700001" in _text(result)
    assert "已设置" not in _text(result) and "绑定已生效" not in _text(result)
    assert app.store.get(actor).player_id == PLAYER
    assert app.service.query.await_count == 1
    result.delivered()
    app.service.record_returned_query.assert_called_once()
    stamp = app.store.get(actor).last_changed_at
    await app.sessions.select("y", app.context, allow_deferred=True)
    assert app.store.get(actor).last_changed_at == stamp
    assert app.pending.player_message == "player:700001"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("answer", ["n", "0", "timeout"])
async def test_explicit_decline_exit_and_timeout_never_bind_or_return_profile(
    tmp_path: Path, platform: Platform, answer: str
) -> None:
    app = runtime(tmp_path, platform)
    await app.operations["seer.player.bind"](app.context.text, app.context)
    if answer == "timeout":
        app.clock.value = 6
    result = await app.sessions.select(
        "y" if answer == "timeout" else answer, app.context, allow_deferred=True
    )
    assert app.store.get(app.context.message.actor).player_id is None
    if result is not None:
        assert (
            "player:700001" not in _text(result)
            if isinstance(result, PortableReply)
            else True
        )
    app.service.record_returned_query.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("answer", ["y", "n"])
async def test_query_binding_suggestion_continues_without_status_prefix(
    tmp_path: Path, platform: Platform, answer: str
) -> None:
    app = runtime(tmp_path, platform, command="米米号700001")
    app.service.query.return_value = PlayerQueryResult(
        pending=app.pending, offer_binding=True
    )
    await app.operations["seer.player.query"](app.context.text, app.context)
    result = await app.sessions.select(answer, app.context, allow_deferred=True)
    assert isinstance(result, PortableReply)
    result = await _after_binding_receipt(result)
    assert "player:700001" in _text(result) and "已设置" not in _text(result)
    assert app.store.get(app.context.message.actor).player_id == (
        PLAYER if answer == "y" else None
    )
    result.delivered()
    app.service.record_returned_query.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("failure", ["permission", "blacklist", "changed", "save"])
async def test_confirmation_rechecks_current_permission_binding_and_write(
    tmp_path: Path, platform: Platform, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = runtime(tmp_path, platform)
    await app.operations["seer.player.bind"](app.context.text, app.context)
    if failure in {"permission", "blacklist"}:
        app.policy[app.context.message.conversation] = (
            frozenset({"blacklist"}) if failure == "blacklist" else frozenset()
        )
    elif failure == "changed":
        app.store.bind(
            actor=app.context.message.actor,
            player_id=600002,
            player_nick="new",
            changed_at=NOW,
        )
    else:

        def fail(**_kwargs: Any) -> None:
            raise OSError

        monkeypatch.setattr(app.store, "bind", fail)
    result = await app.sessions.select("y", app.context, allow_deferred=True)
    assert isinstance(result, PortableReply)
    assert not result.message.request_succeeded
    assert "player:700001" not in _text(result)
    assert app.store.get(app.context.message.actor).player_id == (
        600002 if failure == "changed" else None
    )
    app.service.record_returned_query.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_other_members_and_bots_cannot_confirm(
    tmp_path: Path, platform: Platform
) -> None:
    app = runtime(tmp_path, platform)
    await app.operations["seer.player.bind"](app.context.text, app.context)
    stranger = _context("y", platform=platform, actor_id="other")
    assert await app.sessions.select("y", stranger, allow_deferred=True) is None
    other_bot = replace(
        app.context,
        message=replace(
            app.context.message,
            actor=replace(app.context.message.actor, account_id="other-bot"),
            conversation=replace(
                app.context.message.conversation, account_id="other-bot"
            ),
        ),
    )
    assert await app.sessions.select("y", other_bot, allow_deferred=True) is None
    assert app.store.get(app.context.message.actor).player_id is None


def test_transaction_expected_state_does_not_override_new_binding(
    tmp_path: Path,
) -> None:
    app = runtime(tmp_path, Platform.ONEBOT)
    actor = app.context.message.actor
    expected = app.store.get(actor)
    app.store.bind(actor=actor, player_id=600002, player_nick="other", changed_at=NOW)
    with pytest.raises(PlayerBindingError, match="已变化"):
        app.store.bind(
            actor=actor,
            player_id=PLAYER,
            player_nick="new",
            changed_at=NOW,
            expected_binding=expected,
        )
    assert app.store.get(actor).player_id == OTHER_PLAYER


@pytest.mark.asyncio
@pytest.mark.parametrize("delayed", [False, True])
async def test_binding_success_query_failure_stays_explicit_without_rollback(
    *, delayed: bool
) -> None:
    failed = OutboundMessage.from_text("查询失败", request_succeeded=False)
    delivered = Mock()
    if delayed:
        original = PortableReply(
            OutboundMessage.from_text("正在查询"),
            on_delivered=delivered,
            follow_up=AsyncMock(return_value=failed),
        )
    else:
        original = PortableReply(failed)
    result = binding_query_reply(original, PLAYER)
    if delayed:
        assert "绑定已生效" not in _text(result)
        result.delivered()
        delivered.assert_called_once()
        assert result.follow_up is not None
        message = await result.follow_up()
    else:
        message = result.message
    assert not message.request_succeeded
    assert "绑定已生效" in "".join(getattr(p, "text", "") for p in message.parts)


@pytest.mark.asyncio
async def test_deferred_exception_retains_binding_status_after_router_wrap() -> None:
    original = PortableReply(
        OutboundMessage.from_text("正在查询"),
        follow_up=AsyncMock(side_effect=RuntimeError),
    )
    prepared = binding_query_reply(original, PLAYER)
    # The router installs its common handler after operations prepare replies.
    final = replace(
        prepared,
        on_operation_error=AsyncMock(
            return_value=OutboundMessage.from_text("公共错误")
        ),
    )
    assert final.follow_up is not None
    message = await final.follow_up()
    assert not message.request_succeeded
    assert "绑定已生效" in "".join(getattr(p, "text", "") for p in message.parts)


@pytest.mark.parametrize("days", [0, 1, 3])
def test_prompt_reads_configuration_and_submission_uses_actual_beijing_day(
    tmp_path: Path, days: int
) -> None:
    app = runtime(tmp_path, Platform.ONEBOT)
    app.service._config.player.binding.change_cooldown_days = days
    app.clock.date = datetime(2026, 11, 20, 15, 59, tzinfo=timezone.utc)
    prompt = app.service.shortcut_binding_offer(PLAYER, actor=app.context.message.actor)
    assert (f"换绑冷却为【{days}】" in prompt) is (days > 0)
    app.clock.date += timedelta(minutes=2)
    saved = app.service.bind_shortcut_target(app.context.message.actor, PLAYER)
    assert saved.succeeded
    assert app.store.get(app.context.message.actor).last_changed_at == app.clock.date


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_same_player_query_and_failed_delivery_do_not_rewrite_binding(
    tmp_path: Path, platform: Platform
) -> None:
    app = runtime(tmp_path, platform)
    actor = app.context.message.actor
    app.store.bind(actor=actor, player_id=PLAYER, player_nick="same", changed_at=NOW)
    initial = app.store.get(actor)
    result = await app.operations["seer.player.bind"](app.context.text, app.context)
    assert isinstance(result, PortableReply)
    assert "player:700001" in _text(result) and "是否" not in _text(result)
    result.delivery_failed()
    assert app.store.get(actor) == initial
    app.service.record_returned_query.assert_not_called()
    assert app.service.query.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("delayed", [False, True])
async def test_shortcut_binding_survives_real_immediate_or_deferred_query_failure(
    tmp_path: Path, *, delayed: bool
) -> None:
    app = runtime(tmp_path, Platform.QQ_OFFICIAL, command="收集700001")

    async def query(*_args: Any, **_kwargs: Any) -> QueryReply:
        if delayed:
            await send_request_feedback(queued=True)
        return QueryReply(text="接口失败", complete=False)

    app.service.shortcut = AsyncMock(side_effect=query)
    opened = await app.operations["seer.player.default"](app.context.text, app.context)
    assert isinstance(opened, PortableReply)
    assert "北京时间自然日" in _text(opened)
    result = await app.sessions.select("y", app.context, allow_deferred=True)
    assert isinstance(result, PortableReply)
    result = await _after_binding_receipt(result)
    if result.follow_up:
        result.delivered()
        message = await result.follow_up()
    else:
        message = result.message
    assert not message.request_succeeded
    assert "绑定已生效" in "".join(getattr(part, "text", "") for part in message.parts)
    assert app.store.get(app.context.message.actor).player_id == PLAYER
    app.service.shortcut.assert_awaited_once()
    app.service.query.assert_not_awaited()


def test_restore_hint_keeps_original_deadline_and_expired_hint_is_not_future(
    tmp_path: Path,
) -> None:
    app = runtime(tmp_path, Platform.ONEBOT)
    actor = app.context.message.actor
    app.store.bind(
        actor=actor,
        player_id=PLAYER,
        player_nick="old",
        changed_at=NOW - timedelta(days=1),
    )
    app.store.unbind(actor=actor)
    hint = app.service.shortcut_binding_offer(PLAYER, actor=actor)
    assert "恢复原账号沿用原换绑期限，不重新计时。" in hint
    app.clock.date += timedelta(days=4)
    assert "原换绑冷却已结束" in app.service.shortcut_binding_offer(PLAYER, actor=actor)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
@pytest.mark.parametrize("receipt_ok", [True, False])
async def test_separate_receipt_preserves_query_delivery_and_binding(
    tmp_path: Path, platform: Platform, *, receipt_ok: bool
) -> None:
    app = runtime(tmp_path, platform)
    await app.operations["seer.player.bind"](app.context.text, app.context)
    reply = await app.sessions.select("y", app.context, allow_deferred=True)
    assert isinstance(reply, PortableReply)
    messages: list[str] = []

    async def send(message: OutboundMessage) -> SendResult:
        messages.append("".join(getattr(part, "text", "") for part in message.parts))
        if len(messages) == 1:
            app.service.record_returned_query.assert_not_called()
            if not receipt_ok:
                return SendResult(delivered=False, error_code="temporary")
        return SendResult(delivered=True, message_id=str(len(messages)))

    assert await deliver_portable_reply(reply, send)
    receipt_and_profile = 2
    assert len(messages) == receipt_and_profile
    assert messages[0].startswith("已设置默认米米号：700001")
    assert "2026-11-23 00:00" in messages[0]
    assert "player:700001" in messages[1] and "已设置" not in messages[1]
    app.service.record_returned_query.assert_called_once()
    assert app.store.get(app.context.message.actor).player_id == PLAYER
    app.service.query.assert_awaited_once()


@pytest.mark.parametrize("days", [0, 3])
def test_shared_confirmation_template_and_saved_deadline(
    tmp_path: Path, days: int
) -> None:
    app = runtime(tmp_path, Platform.ONEBOT)
    actor = app.context.message.actor
    app.service._config.player.binding.change_cooldown_days = days
    assert app.service.binding_offer(
        app.pending, actor=actor
    ) == app.service.shortcut_binding_offer(PLAYER, actor=actor)
    app.store.bind(actor=actor, player_id=PLAYER, player_nick="old", changed_at=NOW)
    app.store.unbind(actor=actor)
    app.clock.date += timedelta(days=1)
    assert app.service.bind_shortcut_target(actor, PLAYER).succeeded
    text = app.service.binding_success_notice(actor)
    if days:
        assert text == (
            "已设置默认米米号：700001。\n"
            "可再次换绑时间：2026-11-23 00:00。\n"
            "解除绑定：解绑米米号（解绑不重置冷却）。"
        )
    else:
        assert text == "已设置默认米米号：700001。\n解除绑定：解绑米米号。"
