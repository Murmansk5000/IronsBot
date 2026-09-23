from pathlib import Path

import pytest

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.storage.official_addresses import SqliteOfficialAddressStore
from ironsbot.services.identity_link_store import (
    CrossPlatformIdentityLink,
    OfficialIdentity,
)
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.official_addresses import OfficialAddressService
from ironsbot.services.private_conversation_routes import PrivateConversationRoutes


@pytest.mark.asyncio
async def test_address_sources_are_independent_deduplicated_and_durable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite"
    store = SqliteOfficialAddressStore(path)
    await store.observe(OfficialIdentity("app", "member", "same"), now=1)
    rows = await store.all_addresses()
    assert rows[0].member_seen and not rows[0].private_seen
    await store.observe(OfficialIdentity("app", "user", "same"), now=2)
    await store.observe(OfficialIdentity("app", "user", "same"), now=1)
    await store.observe(OfficialIdentity("other", "user", "same"), now=3)
    rows = await SqliteOfficialAddressStore(path).all_addresses()
    assert len(rows) == len(("app", "other"))
    common = next(r for r in rows if r.app_id == "app")
    assert (common.member_seen_at, common.private_seen_at) == (1, 2)


@pytest.mark.asyncio
async def test_member_binding_is_reused_as_private_address_within_same_app(
    tmp_path: Path,
) -> None:
    principals = IdentityPrincipalService()
    link = CrossPlatformIdentityLink(
        "123456", OfficialIdentity("app", "member", "same"), 1
    )
    principals.register_identity_link(link)
    routes = PrivateConversationRoutes(
        onebot_enabled=False, official_accounts=frozenset({"app", "other"})
    )
    store = SqliteOfficialAddressStore(tmp_path / "state.sqlite")
    service = OfficialAddressService(
        store, principals, routes.register, routes.unregister
    )
    source = ConversationRef(Platform.ONEBOT, "private", "123456")
    await service.load((link,))
    assert routes.resolve(source).id == "same"
    assert routes.resolve(source).account_id == "app"
    for app, address in (("other", "same"), ("app", "different"), ("app", "same")):
        target = ConversationRef(
            Platform.QQ_OFFICIAL, "private", address, account_id=app
        )
        await service.observe(
            IncomingMessageRef(
                Platform.QQ_OFFICIAL,
                ActorRef(Platform.QQ_OFFICIAL, address, account_id=app),
                target,
                "m",
                "",
            )
        )
        resolved = routes.resolve(source)
        assert resolved.id == "same"
        assert resolved.account_id == "app"
    routes.unregister(
        CrossPlatformIdentityLink("123456", OfficialIdentity("app", "user", "same"), 2)
    )
    await OfficialAddressService(
        store, principals, routes.register, routes.unregister
    ).load((link,))
    assert routes.resolve(source).id == "same"
    principals.unregister_identity_link(link)
    service.refresh()
    assert routes.resolve(source) == source
