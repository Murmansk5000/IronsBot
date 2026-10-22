from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from nonebot.matcher import Matcher
from nonebot.message import handle_event

from ironsbot.config.models.messaging import TeamAuditWelcomeConfig
from ironsbot.config.models.settings import MatcherPriorityConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.outbound import MentionPart, SendResult
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.onebot.notice_ingress import OneBotNoticeIngress
from ironsbot.integrations.storage.team_audit import SqliteTeamAuditReminderStore
from ironsbot.plugins.onebot.team_audit import install
from ironsbot.services.team.audit import TeamAuditService
from ironsbot.services.team.audit_policy import FeatureTeamAuditPolicy
from tests.helpers.onebot_events import group_increase_notice_event

if TYPE_CHECKING:
    from pathlib import Path
    from types import SimpleNamespace

pytest_plugins = ("tests.test_shared_onebot_ingress",)


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize("own_account", [False, True])
@pytest.mark.parametrize("source", ["native", "raw"])
async def test_real_group_increase_uses_public_service_and_policy(  # noqa: PLR0913 - real source, role and storage matrix
    runtime: SimpleNamespace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    allowed: bool,
    own_account: bool,
    source: str,
) -> None:
    conversation = ConversationRef(Platform.ONEBOT, "group", "456")
    features = FeatureService(
        {conversation: frozenset({"team_audit"})} if allowed else {}, {}, frozenset()
    )
    store = SqliteTeamAuditReminderStore(
        tmp_path / "audit.sqlite", spawn=asyncio.create_task
    )
    messenger = Mock(
        send=AsyncMock(return_value=SendResult(delivered=True, message_id="sent"))
    )
    service = TeamAuditService(
        TeamAuditWelcomeConfig(enabled=True, followup_enabled=True),
        store,
        FeatureTeamAuditPolicy(features),
        messenger,
        Mock(),
    )
    legacy_send = AsyncMock(side_effect=AssertionError("matcher send used"))
    monkeypatch.setattr(Matcher, "send", legacy_send)
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.start(paused=True)
    try:
        runtime.factory.priorities.team_audit = 0
        install(runtime.factory, scheduler, service)
        event = group_increase_notice_event(user_id=1 if own_account else 101)
        if source == "native":
            await handle_event(runtime.bot, event)
        else:
            ingress = OneBotNoticeIngress(
                runtime.admission,
                runtime.messenger,
                scheduler,
                MatcherPriorityConfig(),
                audit=service,
            )
            await ingress.handle(runtime.bot, event.model_dump())
        if allowed and not own_account:
            messenger.send.assert_awaited_once()
            assert messenger.send.call_args.args[0] == conversation
            message = messenger.send.call_args.args[1]
            assert isinstance(message.parts[0], MentionPart)
            (reminder,) = await store.list_all()
            assert message.parts[0].actor == reminder.actor
            assert reminder.actor.id == "101"
            assert reminder.actor.scope_id == "456"
            assert len(scheduler.get_jobs()) == 1
        else:
            messenger.send.assert_not_awaited()
            assert (await store.list_all()) == []
            assert scheduler.get_jobs() == []
        legacy_send.assert_not_awaited()
    finally:
        scheduler.shutdown(wait=False)
        await asyncio.sleep(0)
