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
from ironsbot.services.identity_link_store import (
    GroupLinkConflictError,
    OfficialIdentity,
)
from ironsbot.services.identity_observation import (
    IdentityObservationAccount,
    OneBotReplyObservation,
    SilentIdentityObservationService,
)
from ironsbot.services.portable_commands import DIRECT_COMMAND_HELP_HINT_TEXT
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from pathlib import Path

APP_ID = "official-app"
OFFICIAL_GROUP = "official-group"
ONEBOT_GROUP = 10001
OFFICIAL_BOT_QQ = 20002
MEMBER_QQ = 30003


def _incoming(
    message_id: str,
    *,
    app_id: str = APP_ID,
    official_group: str = OFFICIAL_GROUP,
    member_openid: str = "member-openid",
) -> IncomingMessageRef:
    return IncomingMessageRef(
        Platform.QQ_OFFICIAL,
        ActorRef(
            Platform.QQ_OFFICIAL,
            member_openid,
            kind="member",
            account_id=app_id,
            scope_id=official_group,
        ),
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            official_group,
            account_id=app_id,
        ),
        message_id,
        "帮助",
    )


def _observed_reply(
    *,
    sender: int = OFFICIAL_BOT_QQ,
    text: str = "结果",
) -> GroupMessageEvent:
    message = Message(MessageSegment.text(text))
    return group_message_event(
        text=text,
        user_id=sender,
        group_id=ONEBOT_GROUP,
        message=message,
        original_message=message,
        reply_sender_user_id=MEMBER_QQ,
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
async def test_normal_command_reply_discovers_group_without_configured_openid(
    tmp_path: Path,
) -> None:
    clock = [100.0]
    store = SqliteIdentityLinkStore(tmp_path / "identity.sqlite")
    linked_groups = []
    service = SilentIdentityObservationService(
        store,
        {
            APP_ID: IdentityObservationAccount(
                APP_ID,
                OFFICIAL_BOT_QQ,
                {},
                frozenset({ONEBOT_GROUP}),
            )
        },
        clock=lambda: clock[0],
        on_group_link=linked_groups.append,
    )

    assert (
        service.record_official_reply(
            _incoming("normal-command"),
            OutboundMessage.from_text("正常指令结果"),
        )
        is not None
    )
    assert await service.observe_onebot(_observation(text="正常指令结果"))

    assert len(linked_groups) == 1
    link = linked_groups[0]
    assert link.onebot_group_id == str(ONEBOT_GROUP)
    assert link.official_group_openid == OFFICIAL_GROUP
    assert service.accounts[APP_ID].groups[OFFICIAL_GROUP] == ONEBOT_GROUP
    assert await store.all_group_links() == (link,)
    restarted_store = SqliteIdentityLinkStore(tmp_path / "identity.sqlite")
    assert await restarted_store.all_group_links() == (link,)


@pytest.mark.asyncio
async def test_addressed_hint_uses_the_same_reply_observation_path(
    tmp_path: Path,
) -> None:
    clock = [100.0]
    store = SqliteIdentityLinkStore(tmp_path / "identity.sqlite")
    service = SilentIdentityObservationService(
        store,
        {
            APP_ID: IdentityObservationAccount(
                APP_ID,
                OFFICIAL_BOT_QQ,
                {},
                frozenset({ONEBOT_GROUP}),
            )
        },
        clock=lambda: clock[0],
    )
    hint = OutboundMessage.from_text(DIRECT_COMMAND_HELP_HINT_TEXT)

    service.record_official_reply(_incoming("mention-1"), hint)
    assert await service.observe_onebot(
        _observation(text=DIRECT_COMMAND_HELP_HINT_TEXT)
    )

    group_links = await store.all_group_links()
    assert len(group_links) == 1
    assert group_links[0].onebot_group_id == str(ONEBOT_GROUP)
    linked = await store.for_official(
        OfficialIdentity(APP_ID, "member", "member-openid", OFFICIAL_GROUP)
    )
    assert linked is not None
    assert linked.onebot_qq_id == str(MEMBER_QQ)


@pytest.mark.asyncio
async def test_group_discovery_does_not_require_member_mention(tmp_path: Path) -> None:
    clock = [100.0]
    store = SqliteIdentityLinkStore(tmp_path / "identity.sqlite")
    service = SilentIdentityObservationService(
        store,
        {
            APP_ID: IdentityObservationAccount(
                APP_ID,
                OFFICIAL_BOT_QQ,
                {},
                frozenset({ONEBOT_GROUP}),
            )
        },
        clock=lambda: clock[0],
    )
    service.record_official_reply(
        _incoming("normal-command"),
        OutboundMessage.from_text("正文结果"),
    )

    assert await service.observe_onebot(
        OneBotReplyObservation(
            OFFICIAL_BOT_QQ,
            ONEBOT_GROUP,
            (),
            "正文结果",
        )
    )
    assert len(await store.all_group_links()) == 1
    assert (
        await store.for_official(
            OfficialIdentity(APP_ID, "member", "member-openid", OFFICIAL_GROUP)
        )
        is None
    )


@pytest.mark.asyncio
async def test_group_discovery_rejects_unconfigured_or_ambiguous_groups(
    tmp_path: Path,
) -> None:
    clock = [100.0]
    store = SqliteIdentityLinkStore(tmp_path / "identity.sqlite")
    service = SilentIdentityObservationService(
        store,
        {
            APP_ID: IdentityObservationAccount(
                APP_ID,
                OFFICIAL_BOT_QQ,
                {},
                frozenset({ONEBOT_GROUP}),
            )
        },
        clock=lambda: clock[0],
    )
    message = OutboundMessage.from_text("相同结果")
    service.record_official_reply(_incoming("first", official_group="group-a"), message)
    service.record_official_reply(
        _incoming("second", official_group="group-b"), message
    )

    assert not await service.observe_onebot(_observation(text="相同结果"))
    assert await store.all_group_links() == ()

    outside = OneBotReplyObservation(
        OFFICIAL_BOT_QQ,
        ONEBOT_GROUP + 1,
        (str(MEMBER_QQ),),
        "相同结果",
    )
    assert not await service.observe_onebot(outside)
    assert await store.all_group_links() == ()


@pytest.mark.asyncio
async def test_group_link_conflicts_never_overwrite_existing_mapping(
    tmp_path: Path,
) -> None:
    store = SqliteIdentityLinkStore(tmp_path / "identity.sqlite")
    first = await store.link_group_verified(
        onebot_group_id=str(ONEBOT_GROUP),
        official_app_id=APP_ID,
        official_group_openid=OFFICIAL_GROUP,
        now=100.0,
    )

    with pytest.raises(GroupLinkConflictError):
        await store.link_group_verified(
            onebot_group_id=str(ONEBOT_GROUP + 1),
            official_app_id=APP_ID,
            official_group_openid=OFFICIAL_GROUP,
            now=101.0,
        )
    with pytest.raises(GroupLinkConflictError):
        await store.link_group_verified(
            onebot_group_id=str(ONEBOT_GROUP),
            official_app_id=APP_ID,
            official_group_openid="another-official-group",
            now=101.0,
        )

    assert await store.all_group_links() == (first,)


@pytest.mark.asyncio
async def test_one_exact_observation_links_group_member_silently(
    tmp_path: Path,
) -> None:
    clock = [100.0]
    service, store = _service(tmp_path, clock)

    service.record_official_reply(
        _incoming("official-1"),
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
async def test_duplicate_napcat_observation_does_not_count_twice(
    tmp_path: Path,
) -> None:
    clock = [100.0]
    service, store = _service(tmp_path, clock)
    observation = _observation()

    service.record_official_reply(
        _incoming("official-1"),
        OutboundMessage.from_text("结果"),
    )
    assert await service.observe_onebot(observation)
    assert not await service.observe_onebot(observation)

    link = await store.for_official(
        OfficialIdentity(APP_ID, "member", "member-openid", OFFICIAL_GROUP)
    )
    assert link is not None
    assert link.onebot_qq_id == str(MEMBER_QQ)


@pytest.mark.asyncio
async def test_observations_are_isolated_by_trusted_bot_and_app_id(
    tmp_path: Path,
) -> None:
    second_app_id = "official-app-b"
    second_group = "official-group-b"
    second_bot_qq = 20003
    second_member = "member-openid-b"
    clock = [100.0]
    store = SqliteIdentityLinkStore(tmp_path / "identity.sqlite")
    service = SilentIdentityObservationService(
        store,
        {
            APP_ID: IdentityObservationAccount(
                APP_ID,
                OFFICIAL_BOT_QQ,
                {OFFICIAL_GROUP: ONEBOT_GROUP},
            ),
            second_app_id: IdentityObservationAccount(
                second_app_id,
                second_bot_qq,
                {second_group: ONEBOT_GROUP},
            ),
        },
        clock=lambda: clock[0],
    )
    message = OutboundMessage.from_text("相同结果")
    service.record_official_reply(_incoming("app-a-1"), message)
    service.record_official_reply(
        _incoming(
            "app-b-1",
            app_id=second_app_id,
            official_group=second_group,
            member_openid=second_member,
        ),
        message,
    )

    second_observation = OneBotReplyObservation(
        second_bot_qq,
        ONEBOT_GROUP,
        (str(MEMBER_QQ),),
        "相同结果",
    )
    assert await service.observe_onebot(second_observation)

    assert (
        await store.for_official(
            OfficialIdentity(APP_ID, "member", "member-openid", OFFICIAL_GROUP)
        )
        is None
    )
    second_link = await store.for_official(
        OfficialIdentity(second_app_id, "member", second_member, second_group)
    )
    assert second_link is not None
    assert second_link.onebot_qq_id == str(MEMBER_QQ)


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
