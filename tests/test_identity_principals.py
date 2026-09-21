from __future__ import annotations

from ironsbot.core.platform import (
    ActorPrincipal,
    ActorRef,
    ConversationPrincipal,
    ConversationRef,
    OfficialUnionIdentity,
    Platform,
)
from ironsbot.services.identity_link_store import (
    CrossPlatformGroupLink,
    CrossPlatformIdentityLink,
    OfficialIdentity,
)
from ironsbot.services.identity_principals import IdentityPrincipalService


def _official_actor(app_id: str, openid: str) -> ActorRef:
    return ActorRef(
        Platform.QQ_OFFICIAL,
        openid,
        account_id=app_id,
    )


def test_union_evidence_unifies_official_app_endpoints() -> None:
    service = IdentityPrincipalService()
    first = _official_actor("app-a", "openid-a")
    second = _official_actor("app-b", "openid-b")
    evidence = OfficialUnionIdentity(union_openid="union-a")

    service.observe_union_identity(actor=first, evidence=evidence)
    service.observe_union_identity(actor=second, evidence=evidence)

    assert service.actor_principal(first) == service.actor_principal(second)
    assert service.actor_principal(first).kind == "official_union"


def test_combined_union_evidence_joins_previously_separate_identifiers() -> None:
    service = IdentityPrincipalService()
    first = _official_actor("app-a", "openid-a")
    second = _official_actor("app-b", "openid-b")
    service.observe_union_identity(
        actor=first,
        evidence=OfficialUnionIdentity(union_openid="union-a"),
    )
    service.observe_union_identity(
        actor=second,
        evidence=OfficialUnionIdentity(union_user_account="account-a"),
    )

    merges = service.observe_union_identity(
        actor=second,
        evidence=OfficialUnionIdentity(
            union_openid="union-a",
            union_user_account="account-a",
        ),
    )

    assert len(merges) == 1
    assert service.actor_principal(first) == service.actor_principal(second)


def test_confirmed_qq_link_becomes_business_principal() -> None:
    service = IdentityPrincipalService()
    first = _official_actor("app-a", "openid-a")
    second = _official_actor("app-b", "openid-b")
    evidence = OfficialUnionIdentity(union_openid="union-a")
    service.observe_union_identity(actor=first, evidence=evidence)
    service.observe_union_identity(actor=second, evidence=evidence)

    merges = service.register_identity_link(
        CrossPlatformIdentityLink(
            "123456",
            OfficialIdentity("app-a", "user", "openid-a"),
            1.0,
        )
    )

    assert len(merges) == 1
    expected = ActorPrincipal("qq", "123456")
    assert service.actor_principal(first) == expected
    assert service.actor_principal(second) == expected


def test_revoked_qq_link_restores_union_principal() -> None:
    service = IdentityPrincipalService()
    first = _official_actor("app-a", "openid-a")
    second = _official_actor("app-b", "openid-b")
    evidence = OfficialUnionIdentity(union_openid="union-a")
    service.observe_union_identity(actor=first, evidence=evidence)
    service.observe_union_identity(actor=second, evidence=evidence)
    link = CrossPlatformIdentityLink(
        "123456",
        OfficialIdentity("app-a", "user", "openid-a"),
        1.0,
    )
    service.register_identity_link(link)

    service.unregister_identity_link(link)

    first_principal = service.actor_principal(first)
    assert first_principal.kind == "official_union"
    assert service.actor_principal(second) == first_principal
    assert service.onebot_actor(first) is None


def test_revoking_one_of_two_confirmed_links_preserves_qq_principal() -> None:
    service = IdentityPrincipalService()
    first = _official_actor("app-a", "openid-a")
    second = _official_actor("app-b", "openid-b")
    evidence = OfficialUnionIdentity(union_openid="union-a")
    service.observe_union_identity(actor=first, evidence=evidence)
    service.observe_union_identity(actor=second, evidence=evidence)
    first_link = CrossPlatformIdentityLink(
        "123456",
        OfficialIdentity("app-a", "user", "openid-a"),
        1.0,
    )
    second_link = CrossPlatformIdentityLink(
        "123456",
        OfficialIdentity("app-b", "user", "openid-b"),
        2.0,
    )
    service.register_identity_link(first_link)
    service.register_identity_link(second_link)

    service.unregister_identity_link(first_link)

    expected = ActorPrincipal("qq", "123456")
    assert service.actor_principal(first) == expected
    assert service.actor_principal(second) == expected


def test_group_link_uses_non_addressable_logical_group() -> None:
    service = IdentityPrincipalService()
    official = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-openid",
        account_id="app-a",
    )

    merges = service.register_group_link(
        CrossPlatformGroupLink("654321", "app-a", "group-openid", 1.0)
    )

    assert len(merges) == 1
    assert merges[0].source.kind == "official_group"
    assert merges[0].target == ConversationPrincipal("qq_group", "654321")
    assert service.conversation_principal(official) == ConversationPrincipal(
        "qq_group",
        "654321",
    )


def test_configured_group_reports_each_endpoint_principal_merge() -> None:
    service = IdentityPrincipalService()

    merges = service.register_configured_group(
        alias="shared",
        onebot_group_id="654321",
        official_endpoints=(
            ("app-a", "group-a"),
            ("app-b", "group-b"),
        ),
    )

    assert {merge.source.kind for merge in merges} == {"official_group"}
    assert {merge.target for merge in merges} == {
        ConversationPrincipal("qq_group", "654321")
    }
    for app_id, group_openid in (("app-a", "group-a"), ("app-b", "group-b")):
        assert service.conversation_principal(
            ConversationRef(
                Platform.QQ_OFFICIAL,
                "group",
                group_openid,
                account_id=app_id,
            )
        ) == ConversationPrincipal("qq_group", "654321")


def test_unlinked_transport_endpoints_remain_distinct() -> None:
    service = IdentityPrincipalService()

    assert service.actor_principal(_official_actor("app-a", "same")) != (
        service.actor_principal(_official_actor("app-b", "same"))
    )
    assert service.actor_principal(ActorRef(Platform.ONEBOT, "123")) == ActorPrincipal(
        "qq",
        "123",
    )
