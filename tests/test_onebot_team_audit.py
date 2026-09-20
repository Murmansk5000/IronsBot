from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ironsbot.config.models.features import (
    FeatureConfig,
    build_feature_service,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.onebot.team_audit import (
    OneBotTeamAuditMembershipProbe,
    OneBotTeamAuditPolicy,
)

GROUP_ID = 987654321
USER_ID = 1234567890
CONVERSATION = ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID))
ACTOR = ActorRef(
    Platform.ONEBOT,
    str(USER_ID),
    kind="member",
    scope_id=str(GROUP_ID),
)


@dataclass
class FakeRouter:
    bot: object | None
    calls: list[ConversationRef]

    def for_conversation(self, conversation: ConversationRef) -> object | None:
        self.calls.append(conversation)
        return self.bot


@dataclass
class FakeGroupProbe:
    access_allowed: bool = True
    member_present: bool = True
    access_calls: list[tuple[object, int]] | None = None
    member_calls: list[tuple[object, int, int]] | None = None

    def __post_init__(self) -> None:
        self.access_calls = []
        self.member_calls = []

    async def can_access(self, bot: object, *, group_id: int) -> bool:
        assert self.access_calls is not None
        self.access_calls.append((bot, group_id))
        return self.access_allowed

    async def has_member(
        self,
        bot: object,
        *,
        group_id: int,
        user_id: int,
    ) -> bool:
        assert self.member_calls is not None
        self.member_calls.append((bot, group_id, user_id))
        return self.member_present


def _policy() -> OneBotTeamAuditPolicy:
    return OneBotTeamAuditPolicy(
        build_feature_service(
            FeatureConfig(group_policy={str(GROUP_ID): ["team_audit"]}),
            frozenset(),
        )
    )


def test_onebot_team_audit_policy_only_enables_configured_group() -> None:
    assert _policy().enabled_for(CONVERSATION)
    assert not _policy().enabled_for(
        ConversationRef(Platform.ONEBOT, "group", "876543210")
    )
    assert not _policy().enabled_for(
        ConversationRef(Platform.QQ_OFFICIAL, "guild", "guild-1")
    )


def test_onebot_team_audit_membership_probe_routes_platform_refs() -> None:
    bot = object()
    router = FakeRouter(bot, [])
    group_probe = FakeGroupProbe()
    probe = OneBotTeamAuditMembershipProbe(router, group_probe)  # type: ignore[arg-type]

    assert asyncio.run(probe.can_access(CONVERSATION))
    assert asyncio.run(probe.has_member(CONVERSATION, actor=ACTOR))
    assert router.calls == [CONVERSATION, CONVERSATION]
    assert group_probe.access_calls == [(bot, GROUP_ID)]
    assert group_probe.member_calls == [(bot, GROUP_ID, USER_ID)]


def test_onebot_team_audit_membership_probe_rejects_incompatible_refs() -> None:
    router = FakeRouter(object(), [])
    group_probe = FakeGroupProbe()
    probe = OneBotTeamAuditMembershipProbe(router, group_probe)  # type: ignore[arg-type]
    official_conversation = ConversationRef(Platform.QQ_OFFICIAL, "guild", "guild-1")

    assert not asyncio.run(probe.can_access(official_conversation))
    assert not asyncio.run(
        probe.has_member(
            CONVERSATION,
            actor=ActorRef(Platform.ONEBOT, str(USER_ID)),
        )
    )
    assert group_probe.access_calls == []
    assert group_probe.member_calls == []
