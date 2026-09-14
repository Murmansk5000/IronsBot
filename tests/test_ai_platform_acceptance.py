from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from ironsbot.config.models.messaging import PushUnsubscribeConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.messaging import AiIntentAction
from ironsbot.core.outbound import OutboundMessage, ReplyContext, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.promotions import PromotionCatalog
from ironsbot.integrations.storage.ai_memory import SqliteAiMemoryStore
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.ai.actions import AiIntentActionExecutor
from ironsbot.services.ai.responses import AiResponseResult
from ironsbot.services.ai.service import REQUEST_FAILED_REPLY, AiService, _chat_key
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from ironsbot.services.messaging.admin_notice_delivery import OutboundAdminNoticeSender
from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
from tests.helpers.ai import FakeAiCompletionClient, ai_config
from tests.helpers.fake_official_platform import FakeOfficialPlatform

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.config.models.ai import AiConfig
    from ironsbot.services.ai.history import HistoryMessage

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
OFFICIAL = Platform.QQ_OFFICIAL
GROUP = ConversationRef(OFFICIAL, "group", "group:opaque")
ACTOR = ActorRef(OFFICIAL, "member:opaque", "member", GROUP.id)


def _service(
    path: Path,
    prompts: list[list[HistoryMessage]],
    *,
    transport: FakeOfficialPlatform | None = None,
    features: FeatureService | None = None,
    result: AiResponseResult | None = None,
) -> AiService:
    config = ai_config(memory=True, history_turns=3)
    policy = features or FeatureService({}, {}, frozenset())
    delivery = ProactiveMessageDelivery(
        transport or FakeOfficialPlatform(NOW),
        policy,
        PromotionCatalog({}),
        PushUnsubscribeStore(path / "state.sqlite"),
        PushUnsubscribeConfig(),
    )

    async def complete(
        _config: AiConfig, messages: list[HistoryMessage]
    ) -> AiResponseResult:
        prompts.append(messages)
        return result or AiResponseResult(status_code=200, reply="model answer")

    return AiService(
        config,
        policy,
        AdminNoticeService(policy, OutboundAdminNoticeSender(delivery)),
        (),
        FakeAiCompletionClient(config, complete),
        SqliteAiMemoryStore(path / "memory.sqlite"),
    )


@pytest.mark.asyncio
async def test_distinct_scoped_actors_cannot_share_short_history(
    tmp_path: Path,
) -> None:
    # Both scopes match their groups. The former colon-joined keys were identical.
    marker = f"actor:{OFFICIAL}:member:"
    first_group = ConversationRef(OFFICIAL, "group", "group")
    second_group = ConversationRef(OFFICIAL, "group", f"group:{marker}group:next")
    first = ActorRef(
        OFFICIAL, f"next:{marker}{second_group.id}:member", "member", first_group.id
    )
    second = ActorRef(OFFICIAL, "member", "member", second_group.id)
    prompts: list[list[HistoryMessage]] = []
    service = _service(tmp_path, prompts)

    await service.chat_reply(
        actor=first, conversation=first_group, prompt="first secret"
    )
    await service.chat_reply(
        actor=second, conversation=second_group, prompt="second query"
    )

    assert "first secret" not in str(prompts[-1])
    assert prompts[-1][-1] == {"role": "user", "content": "second query"}


def test_chat_keys_are_structural_stable_and_lossless() -> None:
    actor = ActorRef(OFFICIAL, '用户:[]"\\', "member", "scope:[]")
    conversation = ConversationRef(OFFICIAL, "group", actor.scope_id or "")
    assert json.loads(_chat_key(actor, conversation)) == [
        [OFFICIAL.value, "group", conversation.id],
        [OFFICIAL.value, "member", actor.scope_id, actor.id],
    ]
    identities = (
        (actor, conversation),
        (replace(actor, id="different"), conversation),
        (replace(actor, scope_id="different"), conversation),
        (ActorRef(OFFICIAL, actor.id), conversation),
        (replace(actor, platform=Platform.ONEBOT), conversation),
        (actor, replace(conversation, platform=Platform.ONEBOT)),
        (actor, replace(conversation, kind="channel")),
        (actor, replace(conversation, id="different")),
    )
    keys = {_chat_key(actor, conversation) for actor, conversation in identities}
    assert len(keys) == len(identities)
    assert _chat_key(actor, conversation) == _chat_key(
        replace(actor), replace(conversation)
    )


@pytest.mark.asyncio
async def test_memory_survives_restart_without_cross_scope_leaks(
    tmp_path: Path,
) -> None:
    prompts: list[list[HistoryMessage]] = []
    first = _service(tmp_path, prompts)
    await first.chat_reply(actor=ACTOR, conversation=GROUP, prompt="remember this")

    restarted = _service(tmp_path, prompts)
    await restarted.chat_reply(actor=ACTOR, conversation=GROUP, prompt="recall")
    assert "remember this" in str(prompts[-1])
    await restarted.chat_reply(actor=ACTOR, conversation=GROUP, prompt="follow up")
    assert sum(message["content"].count("recall") for message in prompts[-1]) == 1

    foreign_group = replace(GROUP, id="another:scope")
    await restarted.chat_reply(
        actor=replace(ACTOR, scope_id=foreign_group.id),
        conversation=foreign_group,
        prompt="foreign query",
    )
    assert "remember this" not in str(prompts[-1])
    assert "recall" not in str(prompts[-1])
    for actor, conversation in (
        (ActorRef(OFFICIAL, ACTOR.id), GROUP),
        (
            replace(ACTOR, platform=Platform.ONEBOT),
            replace(GROUP, platform=Platform.ONEBOT),
        ),
    ):
        await restarted.chat_reply(
            actor=actor, conversation=conversation, prompt="isolated"
        )
        assert "remember this" not in str(prompts[-1])
        assert "recall" not in str(prompts[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_actual_ai_result_obeys_transport_reply_window(
    tmp_path: Path, *, expired: bool
) -> None:
    transport = FakeOfficialPlatform(NOW)
    service = _service(tmp_path, [], transport=transport)
    incoming = IncomingMessageRef(
        OFFICIAL,
        ACTOR,
        GROUP,
        "opaque:event",
        "query",
        sequence="opaque:sequence",
        reply_deadline=NOW + timedelta(seconds=1),
    )
    reply = await service.chat_reply(
        actor=ACTOR, conversation=GROUP, prompt=incoming.text
    )
    assert reply is not None
    if expired:
        transport.now = NOW + timedelta(seconds=2)
    result = await transport.reply(
        ReplyContext.from_message(incoming), OutboundMessage((TextPart(reply),))
    )
    assert result.delivered is not expired
    assert result.error_code == ("fake_reply_expired" if expired else None)
    assert transport.replies[0].sequence == incoming.sequence


@pytest.mark.asyncio
async def test_configured_ai_action_sequence_crosses_restricted_platform_port(
    tmp_path: Path,
) -> None:
    transport = FakeOfficialPlatform(NOW)
    executor = AiIntentActionExecutor(
        _service(tmp_path, []),
        PromotionCatalog({}),
        Mock(),
    )
    action = AiIntentAction(
        action="team_recommend",
        messages=["审核入口：https://example.test/join", "审核群号：123456"],
    )

    messages = await executor.execute(action, "想加入战队")
    results = [
        await transport.reply(
            ReplyContext.from_message(
                IncomingMessageRef(
                    OFFICIAL,
                    ACTOR,
                    GROUP,
                    f"event:{index}",
                    "想加入战队",
                    sequence=f"sequence:{index}",
                    reply_deadline=NOW + timedelta(seconds=10),
                )
            ),
            message,
        )
        for index, message in enumerate(messages)
    ]

    assert all(result.delivered for result in results)
    assert [message.parts[0] for message in messages] == [
        TextPart("审核入口：https://example.test/join"),
        TextPart("审核群号：123456"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
async def test_ai_error_visibility_and_restricted_admin_notice(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, *, admin: bool
) -> None:
    transport = FakeOfficialPlatform(NOW)
    owner = ActorRef(OFFICIAL, "owner:opaque")
    features = FeatureService(
        {GROUP: frozenset({"admin_notice"})} if admin else {},
        {},
        frozenset({owner}),
    )
    service = _service(
        tmp_path,
        [],
        transport=transport,
        features=features,
        result=AiResponseResult(
            status_code=500, error_kind="http", error_detail="test"
        ),
    )
    reply = await service.chat_reply(actor=ACTOR, conversation=GROUP, prompt="query")
    assert reply == (REQUEST_FAILED_REPLY if admin else None)
    assert transport.attempts == []
    assert "skipped unsupported conversation: platform=qq_official" in caplog.text
