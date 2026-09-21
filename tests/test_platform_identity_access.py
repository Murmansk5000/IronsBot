from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from ironsbot.config.models.messaging import PushUnsubscribeConfig
from ironsbot.core.command_catalog import CommandAccess, CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    Platform,
    reference_digest,
)
from ironsbot.core.promotions import PromotionCatalog
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.identity_link_store import OfficialIdentity
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.messaging.admin_notice_delivery import OutboundAdminNoticeSender
from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
from tests.helpers.fake_official_platform import (
    RESTRICTED_CAPABILITIES,
    FakeOfficialPlatform,
)

if TYPE_CHECKING:
    from pathlib import Path

GROUP = ConversationRef(Platform.QQ_OFFICIAL, "group", "group:open")
MEMBER = ActorRef(Platform.QQ_OFFICIAL, "member:open", "member", GROUP.id)
USER = ActorRef(Platform.QQ_OFFICIAL, "user:open")
PRIVATE = ConversationRef(Platform.QQ_OFFICIAL, "private", USER.id)


@pytest.mark.parametrize(
    ("actor", "conversation"),
    [
        (MEMBER, replace(GROUP, id="foreign:group")),
        (MEMBER, PRIVATE),
        (USER, replace(PRIVATE, id="another:user")),
        (USER, replace(GROUP, platform=Platform.ONEBOT)),
        (USER, replace(GROUP, kind="channel")),
        (USER, replace(GROUP, kind="guild")),
    ],
)
def test_invalid_context_cannot_gain_feature_or_privileged_access(
    actor: ActorRef, conversation: ConversationRef
) -> None:
    policy = FeatureService(
        {conversation: frozenset({"example"})},
        {actor: frozenset({"example"})},
        frozenset({actor}),
    )
    assert not policy.is_feature_allowed(actor, conversation, "example")
    context = CommandContext(actor, conversation, group_role="admin")
    for access in (
        CommandAccess(),
        CommandAccess("group", "group_manager"),
        CommandAccess(audience="superuser"),
        CommandAccess("private"),
    ):
        assert not access.is_available(context, policy)


@pytest.mark.parametrize("platform", list(Platform))
def test_supported_context_keeps_group_and_private_access(platform: Platform) -> None:
    user = replace(USER, platform=platform)
    private = replace(PRIVATE, platform=platform)
    group = replace(GROUP, platform=platform)
    member = replace(MEMBER, platform=platform)
    policy = FeatureService(
        {group: frozenset({"example"})},
        {user: frozenset({"example"})},
        frozenset(),
    )
    for actor, conversation in ((user, private), (user, group), (member, group)):
        assert policy.is_feature_allowed(actor, conversation, "example")
        assert CommandAccess().is_available(CommandContext(actor, conversation), policy)
    assert not CommandAccess("private").is_available(
        CommandContext(member, group), policy
    )


def test_identity_principal_service_exposes_linked_onebot_actor() -> None:
    principals = IdentityPrincipalService()
    official = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-openid",
        "member",
        "group-openid",
        account_id="app-id",
    )
    principals.register_official_link(
        onebot_qq_id="10001",
        official=OfficialIdentity("app-id", "member", "member-openid"),
    )

    assert principals.onebot_actor(official) == ActorRef(Platform.ONEBOT, "10001")


@pytest.mark.asyncio
async def test_scoped_notice_recipient_does_not_abort_other_destinations(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    transport = FakeOfficialPlatform(
        datetime(2026, 9, 5, tzinfo=timezone.utc),
        capabilities=replace(RESTRICTED_CAPABILITIES, can_send_proactively=True),
    )
    delivery = ProactiveMessageDelivery(
        transport,
        FeatureService({}, {}, frozenset()),
        PromotionCatalog({}),
        PushUnsubscribeStore(tmp_path / "state.sqlite"),
        PushUnsubscribeConfig(),
    )
    summary = await OutboundAdminNoticeSender(delivery).send_admin_notice(
        OutboundMessage((TextPart("notice"),)),
        private_actors=(MEMBER, USER),
        group_conversations=(GROUP,),
        subscription_key="test",
        action_name="test notice",
        interval_seconds=0,
    )
    assert summary.succeeded == (USER, GROUP)
    assert summary.failed == (MEMBER,)
    assert [conversation for conversation, _ in transport.attempts] == [PRIVATE, GROUP]
    assert "scoped" in caplog.text
    assert reference_digest(MEMBER.id) in caplog.text
    assert MEMBER.id not in caplog.text
