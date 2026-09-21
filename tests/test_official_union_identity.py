from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    OfficialUnionIdentity,
    Platform,
)
from ironsbot.integrations.storage.identity_links import SqliteIdentityLinkStore
from ironsbot.services.identity_link_store import OfficialIdentity
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.official_union_identity import OfficialUnionIdentityService

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.services.messaging.admin_notice import AdminNoticeService


class _AdminNotices:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, text: str, **_kwargs: object) -> None:
        self.messages.append(text)


def _incoming(app_id: str, openid: str) -> IncomingMessageRef:
    return IncomingMessageRef(
        Platform.QQ_OFFICIAL,
        ActorRef(Platform.QQ_OFFICIAL, openid, account_id=app_id),
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "private",
            openid,
            account_id=app_id,
        ),
        f"message-{app_id}",
        "帮助",
        official_union_identity=OfficialUnionIdentity(
            "shared-union-openid",
            "shared-union-account",
        ),
    )


@pytest.mark.asyncio
async def test_union_service_registers_propagated_links(tmp_path: Path) -> None:
    store = SqliteIdentityLinkStore(tmp_path / "state.sqlite")
    await store.link_verified(
        onebot_qq_id="10001",
        official=OfficialIdentity("app-a", "user", "user-a"),
        now=99.0,
    )
    linked: list[object] = []
    service = OfficialUnionIdentityService(
        store,
        cast("AdminNoticeService", _AdminNotices()),
        IdentityPrincipalService(),
        linked.append,
        clock=lambda: 100.0,
    )

    assert await service.observe(_incoming("app-a", "user-a"))
    assert await service.observe(_incoming("app-b", "user-b"))
    propagated = await store.for_official(
        OfficialIdentity("app-b", "user", "user-b")
    )

    assert propagated is not None
    assert propagated.onebot_qq_id == "10001"
    assert linked


@pytest.mark.asyncio
async def test_union_service_reports_conflict_without_exposing_ids(
    tmp_path: Path,
) -> None:
    store = SqliteIdentityLinkStore(tmp_path / "state.sqlite")
    await store.link_verified(
        onebot_qq_id="10001",
        official=OfficialIdentity("app-a", "user", "user-a"),
        now=98.0,
    )
    await store.link_verified(
        onebot_qq_id="10002",
        official=OfficialIdentity("app-b", "user", "user-b"),
        now=99.0,
    )
    notices = _AdminNotices()
    service = OfficialUnionIdentityService(
        store,
        cast("AdminNoticeService", notices),
        IdentityPrincipalService(),
        lambda _link: None,
        clock=lambda: 100.0,
    )
    assert await service.observe(_incoming("app-a", "user-a"))

    assert not await service.observe(_incoming("app-b", "user-b"))
    assert len(notices.messages) == 1
    assert "user-a" not in notices.messages[0]
    assert "user-b" not in notices.messages[0]
    assert "10001" not in notices.messages[0]
    assert "10002" not in notices.messages[0]
