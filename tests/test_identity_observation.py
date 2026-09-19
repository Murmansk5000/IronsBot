from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.exception import IgnoredException

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.onebot.ingress_policy import OneBotIngressPolicy
from ironsbot.integrations.storage.identity_links import SqliteIdentityLinkStore
from ironsbot.services.identity_link_store import OfficialIdentity
from ironsbot.services.identity_observation import (
    IdentityObservationAccount,
    OneBotReplyObservation,
    SilentIdentityObservationService,
)
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from pathlib import Path

APP_ID = "official-app"
OFFICIAL_GROUP = "official-group"
ONEBOT_GROUP = 10001
OFFICIAL_BOT_QQ = 20002
MEMBER_QQ = 30003


def _incoming(message_id: str) -> IncomingMessageRef:
    return IncomingMessageRef(
        Platform.QQ_OFFICIAL,
        ActorRef(
            Platform.QQ_OFFICIAL,
            "member-openid",
            kind="member",
            account_id=APP_ID,
            scope_id=OFFICIAL_GROUP,
        ),
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            OFFICIAL_GROUP,
            account_id=APP_ID,
        ),
        message_id,
        "帮助",
    )


def _observed_reply(
    *,
    sender: int = OFFICIAL_BOT_QQ,
    text: str = "结果",
) -> GroupMessageEvent:
    message = Message([MessageSegment.at(MEMBER_QQ), MessageSegment.text(text)])
    return group_message_event(
        text=text,
        user_id=sender,
        group_id=ONEBOT_GROUP,
        message=message,
        original_message=message,
    )


def _observation(
    *,
    sender: int = OFFICIAL_BOT_QQ,
    text: str = "结果",
) -> OneBotReplyObservation:
    return OneBotReplyObservation(
        sender,
        ONEBOT_GROUP,
        (str(MEMBER_QQ),),
        text,
    )


def _service(
    tmp_path: Path,
    clock: list[float],
) -> tuple[SilentIdentityObservationService, SqliteIdentityLinkStore]:
    store = SqliteIdentityLinkStore(tmp_path / "identity.sqlite")
    service = SilentIdentityObservationService(
        store,
        {
            APP_ID: IdentityObservationAccount(
                APP_ID,
                OFFICIAL_BOT_QQ,
                {OFFICIAL_GROUP: ONEBOT_GROUP},
            )
        },
        clock=lambda: clock[0],
    )
    return service, store


@pytest.mark.asyncio
async def test_two_unique_observations_link_group_member_silently(
    tmp_path: Path,
) -> None:
    clock = [100.0]
    service, store = _service(tmp_path, clock)

    service.record_official_reply(
        _incoming("official-1"),
        OutboundMessage.from_text("结果"),
    )
    assert not await service.observe_onebot(_observation())

    clock[0] += 1
    service.record_official_reply(
        _incoming("official-2"),
        OutboundMessage.from_text("结果"),
    )
    assert await service.observe_onebot(_observation())

    link = await store.for_official(
        OfficialIdentity(APP_ID, "member", "member-openid", OFFICIAL_GROUP)
    )
    assert link is not None
    assert link.onebot_qq_id == str(MEMBER_QQ)
    assert link.official.scope_id == ""


@pytest.mark.asyncio
async def test_observed_member_link_is_shared_across_groups(tmp_path: Path) -> None:
    store = SqliteIdentityLinkStore(tmp_path / "identity.sqlite")
    await store.link_verified(
        onebot_qq_id=str(MEMBER_QQ),
        official=OfficialIdentity(
            APP_ID,
            "member",
            "member-openid",
            "first-group",
        ),
        now=100.0,
    )

    link = await store.for_official(
        OfficialIdentity(APP_ID, "member", "member-openid", "second-group")
    )

    assert link is not None
    assert link.onebot_qq_id == str(MEMBER_QQ)
    assert link.official.scope_id == ""


@pytest.mark.asyncio
async def test_untrusted_or_ambiguous_messages_never_link(tmp_path: Path) -> None:
    clock = [100.0]
    service, store = _service(tmp_path, clock)
    message = OutboundMessage.from_text("结果")
    service.record_official_reply(_incoming("official-1"), message)

    assert not await service.observe_onebot(_observation(sender=99999))
    service.record_official_reply(_incoming("official-2"), message)
    assert not await service.observe_onebot(_observation())
    assert (
        await store.for_official(
            OfficialIdentity(APP_ID, "member", "member-openid", OFFICIAL_GROUP)
        )
        is None
    )


@pytest.mark.asyncio
async def test_silent_ingress_observes_then_blocks_onebot_event(
    tmp_path: Path,
) -> None:
    clock = [100.0]
    service, _store = _service(tmp_path, clock)
    incoming = _incoming("official-1")
    service.record_official_reply(incoming, OutboundMessage.from_text("结果"))
    policy = OneBotIngressPolicy(
        messages_enabled=False,
        identity_observer=service,
    )

    with pytest.raises(IgnoredException):
        await policy.process(_observed_reply())


@pytest.mark.asyncio
async def test_interactive_ingress_allows_onebot_event(tmp_path: Path) -> None:
    clock = [100.0]
    service, _store = _service(tmp_path, clock)
    event = _observed_reply()

    await OneBotIngressPolicy(
        messages_enabled=True,
        identity_observer=service,
    ).process(event)
