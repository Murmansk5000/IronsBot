from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.core.outbound import OutboundMessage
from ironsbot.integrations.storage.identity_links import SqliteIdentityLinkStore
from ironsbot.services.identity_link_store import (
    CrossPlatformIdentityLink,
    OfficialIdentity,
)
from ironsbot.services.identity_mutations import IdentityMutationCoordinator
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.official_union_identity import OfficialUnionIdentityService
from tests.test_identity_observation import (
    APP_ID,
    MEMBER_QQ,
    OFFICIAL_BOT_QQ,
    ONEBOT_GROUP,
    _incoming,
    _observation,
    _service,
)
from tests.test_identity_publication import _block_commits
from tests.test_official_union_identity import _incoming as union_incoming

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["reply", "original", "group_reply"])
async def test_observed_identity_publishes_after_caller_cancels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    service, store = _service(tmp_path, [100.0])
    await store.all_links()
    principals = IdentityPrincipalService()
    published: list[str] = []

    def on_link(qq_id: str, official: OfficialIdentity) -> None:
        principals.register_identity_link(
            CrossPlatformIdentityLink(qq_id, official, 100)
        )
        published.append("member")

    def on_group(_link: object) -> None:
        published.append("group")

    service.on_link = on_link
    service.on_group_link = on_group
    incoming = _incoming("official-message")
    if source == "original":
        await service.observe_onebot(
            _observation(
                sender=MEMBER_QQ, text="帮助", mentions=(str(OFFICIAL_BOT_QQ),)
            )
        )
    else:
        if source == "group_reply":
            service.accounts = {
                APP_ID: replace(
                    service.accounts[APP_ID],
                    groups={},
                    candidate_onebot_group_ids=frozenset({ONEBOT_GROUP}),
                )
            }
        service.record_reply(incoming, OutboundMessage.from_text("结果"))
    entered, release, committed = _block_commits(monkeypatch)

    async def observe() -> bool:
        if source == "original":
            return await service.observe_official_message(
                incoming, explicitly_addressed=True
            )
        return await service.observe_onebot(_observation())

    pending = asyncio.create_task(observe())
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        pending.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert committed.is_set()
        assert published == (
            ["group", "member"] if source == "group_reply" else ["member"]
        )
        assert principals.actor_principal(incoming.actor).id == str(MEMBER_QQ)
        assert len(await store.all_links()) == 1
        if source == "group_reply":
            assert len(await store.all_group_links()) == 1
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_union_evidence_publishes_after_caller_cancels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteIdentityLinkStore(
        tmp_path / "state.sqlite", spawn=asyncio.create_task
    )
    principals = IdentityPrincipalService()
    known = await store.link_verified(
        onebot_qq_id="101", official=OfficialIdentity("app-a", "user", "first"), now=100
    )
    principals.register_identity_link(known)
    linked: list[CrossPlatformIdentityLink] = []
    service = OfficialUnionIdentityService(
        store,
        Mock(send=AsyncMock()),
        principals,
        lambda _merge: None,
        linked.append,
        mutations=IdentityMutationCoordinator(asyncio.create_task),
    )
    await service.observe(union_incoming("app-a", "first"))
    linked.clear()
    incoming = union_incoming("app-b", "second")
    entered, release, committed = _block_commits(monkeypatch)
    pending = asyncio.create_task(service.observe(incoming))
    try:
        await asyncio.wait_for(entered.wait(), timeout=3)
        pending.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert committed.is_set()
        assert sum(link.official.app_id == "app-b" for link in linked) == 1
        assert principals.actor_principal(incoming.actor).id == "101"
        saved = await store.for_official(OfficialIdentity("app-b", "user", "second"))
        assert saved is not None and saved.onebot_qq_id == "101"
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
