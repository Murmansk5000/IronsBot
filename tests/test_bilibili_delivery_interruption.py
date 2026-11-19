from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.delivery_attempt import (
    DeliveryProgress,
    controlled_delivery,
    delivery_progress,
)
from ironsbot.core.outbound import DeliveryFailureKind, OutboundMessage
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.qq_official.api_errors import qq_official_exception_result
from ironsbot.integrations.qq_official.delivery_diagnostics import (
    QQDeliveryClosedError,
    QQDeliveryPhaseError,
    delivery_phase,
)
from ironsbot.integrations.qq_official.message_rendering import QQOfficialTextPayload
from ironsbot.integrations.qq_official.sdk_client import TencentQQClient
from ironsbot.integrations.storage.bilibili_delivery_ledger import (
    SqliteDynamicDeliveryLedger,
)
from ironsbot.integrations.storage.sqlite import SqliteDatabase
from ironsbot.services.bilibili.delivery_ledger import StageMessenger
from ironsbot.services.bilibili.delivery_lifecycle import OrderedStages
from ironsbot.services.bilibili.target_models import BiliPushTargets

if TYPE_CHECKING:
    from pathlib import Path

    from qqbot_agent_sdk.api_client import QQApiClient

    from ironsbot.core.outbound import OutboundMessenger, SendResult
    from ironsbot.integrations.qq_official.media_upload import QQOfficialMediaUpload
    from ironsbot.services.bilibili.delivery_ledger import DynamicDeliveryLedger

TARGET = ConversationRef(Platform.QQ_OFFICIAL, "group", "test")


def _stage(send: AsyncMock) -> tuple[StageMessenger, Mock]:
    ledger = Mock()
    ledger.freeze_unit.side_effect = lambda _dynamic, _target, _stage, message: message
    ledger.claim.return_value = True
    ledger.attempts.return_value = 2
    messenger = Mock(send=send)
    return (
        StageMessenger(
            cast("OutboundMessenger", messenger),
            cast("DynamicDeliveryLedger", ledger),
            "1",
            "image:1",
        ),
        ledger,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase,submitted,expected",
    [
        ("upload_prepare", False, DeliveryFailureKind.RETRYABLE),
        ("message_submit", False, DeliveryFailureKind.UNCERTAIN),
        (None, False, DeliveryFailureKind.UNCERTAIN),
        ("unknown", False, DeliveryFailureKind.UNCERTAIN),
        ("upload_prepare", True, DeliveryFailureKind.UNCERTAIN),
        ("cos_put[1/2]", False, DeliveryFailureKind.RETRYABLE),
    ],
)
async def test_cancel_records_child_task_evidence_and_propagates(
    phase: str | None,
    *,
    submitted: bool,
    expected: DeliveryFailureKind,
) -> None:
    started = asyncio.Event()
    blocked = asyncio.Event()

    async def transport() -> None:
        if submitted:
            async with delivery_phase("message_submit"):
                pass
        if phase is None:
            started.set()
            await blocked.wait()
        else:
            async with delivery_phase(phase):
                started.set()
                await blocked.wait()

    async def send(
        _conversation: ConversationRef, _message: OutboundMessage
    ) -> SendResult:
        # ContextVar values are copied to this child, but evidence must be shared.
        await asyncio.create_task(transport())
        raise AssertionError

    mock_send = AsyncMock(side_effect=send)
    stage, ledger = _stage(mock_send)
    outer = DeliveryProgress()
    token = delivery_progress.set(outer)
    try:
        task = asyncio.create_task(stage.send(TARGET, OutboundMessage.from_text("x")))
        try:
            await asyncio.wait_for(started.wait(), 2)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert delivery_progress.get() is outer
        assert outer.closed
    finally:
        delivery_progress.reset(token)

    ledger.finish.assert_called_once()
    result = cast("SendResult", ledger.finish.call_args.args[3])
    assert result.failure_kind is expected
    assert result.failure_phase == phase
    assert result.error_code == "interrupted_send"
    assert result.attempt_count == ledger.attempts.return_value
    assert not result.delivered
    if expected is DeliveryFailureKind.UNCERTAIN:
        ledger.block_following.assert_called_once_with("1", TARGET, "image:1")
    else:
        ledger.block_following.assert_not_called()
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase,expected",
    [
        (None, DeliveryFailureKind.UNCERTAIN),
        ("upload_prepare", DeliveryFailureKind.RETRYABLE),
        ("message_submit", DeliveryFailureKind.UNCERTAIN),
    ],
)
async def test_raised_exception_requires_actual_phase_evidence(
    phase: str | None, expected: DeliveryFailureKind
) -> None:
    async def send(
        _conversation: ConversationRef, _message: OutboundMessage
    ) -> SendResult:
        if phase is not None:
            async with delivery_phase(phase):
                raise RuntimeError
        raise RuntimeError

    stage, ledger = _stage(AsyncMock(side_effect=send))
    result = await stage.send(TARGET, OutboundMessage.from_text("x"))
    assert result.failure_kind is expected
    assert result.failure_phase == phase
    assert result.attempt_count == ledger.attempts.return_value
    ledger.finish.assert_called_once_with("1", TARGET, "image:1", result)


@pytest.mark.asyncio
async def test_nested_upload_keeps_submission_and_restores_active_phase() -> None:
    progress = DeliveryProgress()
    token = delivery_progress.set(progress)
    try:
        async with delivery_phase("message_submit"):
            async with delivery_phase("upload_prepare"):
                assert progress.phase == "upload_prepare"
                assert not progress.safe_to_retry
            assert progress.phase == "message_submit"
        async with delivery_phase("upload_prepare"):
            assert progress.may_have_submitted
            assert not progress.safe_to_retry
        assert progress.phase is None
        assert progress.may_have_submitted
        assert not progress.safe_to_retry
    finally:
        delivery_progress.reset(token)


@pytest.mark.asyncio
async def test_completed_prepare_is_not_evidence_for_later_generic_exception() -> None:
    async def send(
        _conversation: ConversationRef, _message: OutboundMessage
    ) -> SendResult:
        async with delivery_phase("upload_prepare"):
            pass
        raise RuntimeError

    stage, _ledger = _stage(AsyncMock(side_effect=send))
    result = await stage.send(TARGET, OutboundMessage.from_text("x"))
    assert result.failure_kind is DeliveryFailureKind.UNCERTAIN
    assert result.failure_phase is None


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize("submitted", [False, True])
async def test_closed_or_expired_attempt_blocks_new_phase(
    *, expired: bool, submitted: bool
) -> None:
    progress = DeliveryProgress(
        may_have_submitted=submitted,
        deadline=time.monotonic() - 1 if expired else None,
    )
    if not expired:
        progress.close()
    token = delivery_progress.set(progress)
    try:
        with pytest.raises(QQDeliveryClosedError) as caught:
            async with delivery_phase("message_submit"):
                pytest.fail("closed attempt must never post")
        assert isinstance(caught.value, TimeoutError)
        assert caught.value.requested_phase == "message_submit"
        assert progress.may_have_submitted is submitted
        result = qq_official_exception_result(caught.value)
        assert result.failure_kind is (
            DeliveryFailureKind.UNCERTAIN
            if submitted
            else DeliveryFailureKind.RETRYABLE
        )
        assert progress.safe_to_retry is not submitted
    finally:
        delivery_progress.reset(token)


@pytest.mark.asyncio
async def test_parent_closure_prevents_shielded_worker_from_posting() -> None:
    preparing = asyncio.Event()
    release = asyncio.Event()
    progress = DeliveryProgress()
    post = AsyncMock()

    async def send(
        _conversation: ConversationRef, _message: OutboundMessage
    ) -> SendResult:
        assert delivery_progress.get() is progress
        async with delivery_phase("upload_prepare"):
            preparing.set()
            await release.wait()
        async with delivery_phase("message_submit"):
            await post()
        raise AssertionError

    stage, ledger = _stage(AsyncMock(side_effect=send))
    token = delivery_progress.set(progress)
    try:
        worker = asyncio.create_task(stage.send(TARGET, OutboundMessage.from_text("x")))
    finally:
        delivery_progress.reset(token)
    try:
        await asyncio.wait_for(preparing.wait(), 2)
        progress.close()
    finally:
        release.set()
        result = await worker
    assert result.failure_kind is DeliveryFailureKind.RETRYABLE
    assert result.failure_phase == "pre_submit_gate"
    assert not progress.may_have_submitted
    post.assert_not_awaited()
    ledger.block_following.assert_not_called()
    ledger.finish.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize("valid_receipt", [False, True])
async def test_sdk_preserves_late_receipt_and_validates_after_closure(
    *, expired: bool, valid_receipt: bool
) -> None:
    progress = DeliveryProgress(deadline=time.monotonic() + 60)

    async def post(_target: str, _message: object) -> dict[str, object]:
        assert progress.may_have_submitted
        if expired:
            progress.deadline = time.monotonic() - 1
        else:
            progress.close()
        return {"id": "late-receipt"} if valid_receipt else {}

    api = Mock(
        next_msg_seq=Mock(return_value=1),
        post_group_message=AsyncMock(side_effect=post),
    )
    client = TencentQQClient(
        cast("QQApiClient", api), cast("QQOfficialMediaUpload", AsyncMock())
    )
    token = delivery_progress.set(progress)
    controlled_token = controlled_delivery.set(True)
    try:
        if valid_receipt:
            receipt = await client.send_to_group(
                "target", (QQOfficialTextPayload("x"),)
            )
            assert receipt.id == "late-receipt"
        else:
            with pytest.raises(QQDeliveryPhaseError) as caught:
                await client.send_to_group("target", (QQOfficialTextPayload("x"),))
            assert caught.value.phase == "message_submit"
            assert not isinstance(caught.value, QQDeliveryClosedError)
            assert qq_official_exception_result(caught.value).failure_kind is (
                DeliveryFailureKind.UNCERTAIN
            )
    finally:
        controlled_delivery.reset(controlled_token)
        delivery_progress.reset(token)
    api.post_group_message.assert_awaited_once()
    assert progress.closed


@pytest.mark.asyncio
async def test_sdk_does_not_post_when_attempt_is_already_closed() -> None:
    progress = DeliveryProgress()
    progress.close()
    api = Mock(next_msg_seq=Mock(return_value=1), post_group_message=AsyncMock())
    client = TencentQQClient(
        cast("QQApiClient", api), cast("QQOfficialMediaUpload", AsyncMock())
    )
    token = delivery_progress.set(progress)
    controlled_token = controlled_delivery.set(True)
    try:
        with pytest.raises(QQDeliveryClosedError):
            await client.send_to_group("target", (QQOfficialTextPayload("x"),))
    finally:
        controlled_delivery.reset(controlled_token)
        delivery_progress.reset(token)
    api.post_group_message.assert_not_awaited()
    assert not progress.may_have_submitted


@dataclass
class _OrderedPreSubmit:
    ledger: SqliteDynamicDeliveryLedger
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    post: AsyncMock = field(default_factory=AsyncMock)
    results: list[SendResult] = field(default_factory=list)
    progress: DeliveryProgress | None = None
    worker: asyncio.Task[None] | None = None
    initial_budget: tuple[float, float] | None = None

    def budget(self) -> tuple[float, float]:
        with SqliteDatabase(self.ledger.path).connect() as db:
            row = db.execute(
                "SELECT started_at,deadline_at FROM stages "
                "WHERE dynamic_id='1' AND stage='link'"
            ).fetchone()
        assert row is not None
        return float(row[0]), float(row[1])

    async def send(
        self, _conversation: ConversationRef, _message: OutboundMessage
    ) -> SendResult:
        self.progress = delivery_progress.get()
        assert self.progress is not None
        async with delivery_phase("upload_prepare"):
            self.initial_budget = self.budget()
            self.entered.set()
            await self.release.wait()
        async with delivery_phase("message_submit"):
            await self.post()
        raise AssertionError

    async def operation(self) -> None:
        self.worker = cast("asyncio.Task[None]", asyncio.current_task())
        messenger = Mock(send=AsyncMock(side_effect=self.send))
        stage = StageMessenger(
            cast("OutboundMessenger", messenger), self.ledger, "1", "link"
        )
        self.results.append(await stage.send(TARGET, OutboundMessage.from_text("x")))

    def assert_unsent_budget(self) -> None:
        self.post.assert_not_awaited()
        assert self.ledger.attempts("1", TARGET, "link") == 1
        assert self.budget() == self.initial_budget
        assert self.ledger.stage_state("1", TARGET, "text") == "pending"

    async def drain(self) -> None:
        self.release.set()
        if self.worker is not None:
            await asyncio.wait_for(self.worker, 2)


@pytest.fixture
def ordered_pre_submit(tmp_path: Path) -> _OrderedPreSubmit:
    ledger = SqliteDynamicDeliveryLedger(tmp_path / "ledger.sqlite")
    item = {
        "id_str": "1",
        "modules": {"module_dynamic": {"desc": {"text": "body"}}},
    }
    assert ledger.prepare(
        item, int(time.time()), 123, BiliPushTargets([TARGET], [], [], []), ()
    )
    return _OrderedPreSubmit(ledger)


@pytest.mark.asyncio
async def test_ordered_parent_cancellation_preserves_known_unsent_retry_budget(
    ordered_pre_submit: _OrderedPreSubmit,
) -> None:
    run = ordered_pre_submit
    ordered = OrderedStages(run.ledger, "1", {}, set())
    parent = asyncio.create_task(ordered.run(TARGET, "link", run.operation))
    try:
        await asyncio.wait_for(run.entered.wait(), 2)
        assert run.progress is not None
        assert run.progress.safe_to_retry
        assert run.progress.phase == "upload_prepare"
        parent.cancel()
        with pytest.raises(asyncio.CancelledError):
            await parent
        assert run.progress.closed
        # Cancellation closes the gate but does not expire the shielded attempt.
        assert run.ledger.stage_state("1", TARGET, "link") == "sending"
        assert run.ledger.stage_result("1", TARGET, "link") is None
        assert ordered.failures == {}
        run.assert_unsent_budget()
    finally:
        if not parent.done():
            parent.cancel()
        await asyncio.gather(parent, return_exceptions=True)
        await run.drain()
    assert len(run.results) == 1
    assert run.results[0].failure_kind is DeliveryFailureKind.RETRYABLE
    assert run.results[0].failure_phase == "pre_submit_gate"
    assert run.ledger.stage_state("1", TARGET, "link") == "retry"
    stored = run.ledger.stage_result("1", TARGET, "link")
    assert stored is not None
    assert (stored.failure_kind, stored.failure_phase, stored.attempt_count) == (
        DeliveryFailureKind.RETRYABLE,
        "pre_submit_gate",
        1,
    )
    run.assert_unsent_budget()


@pytest.mark.asyncio
async def test_ordered_timeout_records_permanent_known_unsent_deadline(
    ordered_pre_submit: _OrderedPreSubmit, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = ordered_pre_submit

    async def expire_after_entry(
        shielded: asyncio.Future[None], *, timeout: float
    ) -> None:
        assert timeout > 0
        await run.entered.wait()
        # Expire the real shield wait only after the transport is parked pre-submit.
        await asyncio.wait_for(shielded, timeout=0)

    monkeypatch.setattr(
        "ironsbot.services.bilibili.delivery_lifecycle.asyncio",
        SimpleNamespace(
            ensure_future=asyncio.ensure_future,
            shield=asyncio.shield,
            wait_for=expire_after_entry,
            TimeoutError=asyncio.TimeoutError,
            CancelledError=asyncio.CancelledError,
        ),
    )
    ordered = OrderedStages(run.ledger, "1", {}, set())
    try:
        await asyncio.wait_for(ordered.run(TARGET, "link", run.operation), 2)
        assert run.progress is not None
        assert run.progress.closed
        assert run.progress.safe_to_retry
        result = run.ledger.stage_result("1", TARGET, "link")
        assert result is not None
        assert result.error_code == "stage_deadline_before_submit"
        assert result.failure_kind is DeliveryFailureKind.PERMANENT
        assert result.failure_phase == "upload_prepare"
        assert run.ledger.stage_state("1", TARGET, "link") == "failed"
        assert ordered.failures[(TARGET, "link")] == result
        assert ordered.advance(TARGET, "link")
        run.assert_unsent_budget()
    finally:
        await run.drain()
    assert len(run.results) == 1
    assert run.results[0].failure_kind is DeliveryFailureKind.RETRYABLE
    assert run.results[0].failure_phase == "pre_submit_gate"
    # A late gate rejection must not replace the durable permanent timeout verdict.
    assert run.ledger.stage_result("1", TARGET, "link") == result
    assert run.ledger.stage_state("1", TARGET, "link") == "failed"
    run.assert_unsent_budget()
