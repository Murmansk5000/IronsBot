from dataclasses import replace
from pathlib import Path

from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.bilibili_preferences import (
    SqliteBiliPushPreferenceStore,
)
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.bilibili.preferences import bili_push_subscription_key
from ironsbot.services.bilibili.private_routes import BiliPrivateRoutes
from ironsbot.services.bilibili.target_models import (
    BiliConfiguredTargets,
    BiliTargetRule,
)
from ironsbot.services.identity_link_store import (
    CrossPlatformIdentityLink,
    OfficialIdentity,
)
from ironsbot.services.identity_principals import IdentityPrincipalService
from tests.helpers.bilibili import build_test_bilibili_service

SOURCE = ConversationRef(Platform.ONEBOT, "private", "123456")


def _link(app: str = "app1", *, member: bool = False) -> CrossPlatformIdentityLink:
    return CrossPlatformIdentityLink(
        SOURCE.id,
        OfficialIdentity(app, "member" if member else "user", "openid-" + app),
        1,
    )


def test_member_link_becomes_same_app_private_address() -> None:
    routes = BiliPrivateRoutes(
        onebot_enabled=False,
        official_accounts=frozenset({"app1"}),
        default_account="app1",
    )
    routes.register(_link(member=True))
    assert routes.resolve(SOURCE) == ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        "openid-app1",
        account_id="app1",
    )


def test_verified_user_route_selection_and_unlink() -> None:
    routes = BiliPrivateRoutes(
        onebot_enabled=False,
        official_accounts=frozenset({"app1", "app2"}),
        default_account="app2",
    )
    routes.register(_link())
    assert routes.resolve(SOURCE) == SOURCE
    routes.register(_link("app2"))
    assert routes.resolve(SOURCE).account_id == "app2"
    routes.default_account = "unlinked"
    assert routes.resolve(SOURCE) == SOURCE
    routes.unregister(_link("app2"))
    assert routes.resolve(SOURCE) == SOURCE
    routes.onebot_enabled = True
    assert routes.resolve(SOURCE) == SOURCE
    routes.onebot_enabled = False
    routes.official_accounts = frozenset()
    assert routes.resolve(SOURCE) == SOURCE


def test_private_principal_merges_same_app_member_and_unlinks() -> None:
    principals = IdentityPrincipalService()
    endpoint = ConversationRef(
        Platform.QQ_OFFICIAL, "private", "openid-app1", account_id="app1"
    )
    member_link = _link(member=True)
    assert principals.register_private_link(member_link)
    assert principals.conversation_principal(
        endpoint
    ) == principals.conversation_principal(SOURCE)
    principals.unregister_private_link(member_link)
    assert principals.conversation_principal(
        endpoint
    ) != principals.conversation_principal(SOURCE)


def test_target_conversion_preserves_modes_and_unsubscribe(tmp_path: Path) -> None:
    principals = IdentityPrincipalService()
    link = _link()
    principals.register_identity_link(link)
    principals.register_private_link(link)
    routes = BiliPrivateRoutes(
        onebot_enabled=False, official_accounts=frozenset({"app1"})
    )
    routes.register(link)
    service = build_test_bilibili_service(tmp_path)
    store = PushUnsubscribeStore(
        tmp_path / "state.sqlite", principal_for=principals.conversation_principal
    )
    prefs = SqliteBiliPushPreferenceStore(
        tmp_path / "state.sqlite", principal_for=principals.conversation_principal
    )
    features = FeatureService(
        {},
        {ActorRef(Platform.ONEBOT, SOURCE.id): frozenset({"bili_push"})},
        frozenset(),
        principals=principals,
    )
    targets = replace(
        service.targets,
        features=features,
        private_routes=routes,
        preferences=prefs,
        unsubscribe_store=store,
    )
    endpoint = routes.resolve(SOURCE)
    uid = 912345678
    prefs.set_mode(SOURCE, uid, "link")
    result = targets.push_targets_for_uid(uid)
    assert result.link_private_conversations == [endpoint]
    assert not result.full_private_conversations
    store.unsubscribe(SOURCE, bili_push_subscription_key(uid), "bili_push")
    assert store.is_unsubscribed(endpoint, bili_push_subscription_key(uid))
    assert targets.subscription_options(endpoint)[0].unsubscribed


def test_configured_per_user_accounts_follow_private_route(tmp_path: Path) -> None:
    service = build_test_bilibili_service(tmp_path)
    routes = BiliPrivateRoutes(
        onebot_enabled=False, official_accounts=frozenset({"app1"})
    )
    routes.register(_link())
    endpoint = routes.resolve(SOURCE)
    features = FeatureService(
        {},
        {ActorRef(Platform.ONEBOT, SOURCE.id): frozenset({"bili_push"})},
        frozenset(),
    )
    rule = BiliTargetRule(frozenset({"extra"}), frozenset({99}), "full", "link", {})
    targets = replace(
        service.targets,
        features=features,
        private_routes=routes,
        configured_targets=BiliConfiguredTargets({}, {SOURCE: rule}),
    )
    assert targets.push_targets_for_uid(99).link_private_conversations == [endpoint]
    assert targets.target_rule(endpoint) == rule
    routes.unregister(_link())
    assert targets.push_targets_for_uid(99).link_private_conversations == [SOURCE]
