from __future__ import annotations

# ruff: noqa: PLR2004
import asyncio
import sqlite3
from typing import TYPE_CHECKING

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.storage.identity_links import SqliteIdentityLinkStore
from ironsbot.services.identity_link_commands import IdentityLinkCommands
from ironsbot.services.identity_link_store import (
    IdentityLinkChallengeInvalidError,
    IdentityLinkConflictError,
    OfficialIdentity,
)
from ironsbot.services.identity_linking import (
    IdentityLinkingAccountError,
    IdentityLinkingConflictError,
    IdentityLinkingError,
    IdentityLinkingPlatformError,
    IdentityLinkingService,
    IdentityLinkingTokenError,
    OfficialAccount,
)

if TYPE_CHECKING:
    from pathlib import Path


def _store(path: Path) -> SqliteIdentityLinkStore:
    return SqliteIdentityLinkStore(path)


def _service(
    path: Path,
    *,
    now: list[float] | None = None,
    accounts: dict[str, OfficialAccount] | None = None,
) -> IdentityLinkingService:
    clock = now or [100.0]
    configured = accounts or {
        "main": OfficialAccount("main", "official-app"),
    }
    return IdentityLinkingService(
        _store(path),
        configured,
        challenge_ttl_seconds=60.0,
        clock=lambda: clock[0],
    )


def _onebot(qq_id: str = "1621582661") -> ActorRef:
    return ActorRef(Platform.ONEBOT, qq_id)


def _official_member(
    openid: str = "member-openid",
    *,
    app_id: str = "official-app",
    group_id: str = "group-openid",
) -> ActorRef:
    return ActorRef(
        Platform.QQ_OFFICIAL,
        openid,
        "member",
        group_id,
        app_id,
    )


def _official_user(
    openid: str = "user-openid",
    *,
    app_id: str = "official-app",
) -> ActorRef:
    return ActorRef(Platform.QQ_OFFICIAL, openid, account_id=app_id)


def _context(actor: ActorRef, text: str) -> MessageInputContext:
    conversation = (
        ConversationRef(
            Platform.QQ_OFFICIAL,
            "group",
            actor.scope_id or "group-openid",
            actor.account_id,
        )
        if actor.kind == "member"
        else ConversationRef(
            actor.platform,
            "private",
            actor.id,
            actor.account_id,
        )
    )
    return MessageInputContext(
        IncomingMessageRef(
            actor.platform,
            actor,
            conversation,
            f"message-{text}",
            text,
        ),
        mentions_bot=True,
    )


def _outbound_text(message: OutboundMessage) -> str:
    part = message.parts[0]
    assert isinstance(part, TextPart)
    return part.text


@pytest.mark.asyncio
async def test_service_links_explicit_onebot_and_official_identities(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite"
    service = _service(path)

    challenge = await service.begin(_onebot())
    link = await service.confirm(_official_member(), challenge.token.lower())

    assert challenge.account.alias == "main"
    assert len(challenge.token) == 9
    assert challenge.token[4] == "-"
    assert link.onebot_qq_id == "1621582661"
    assert link.official == OfficialIdentity(
        "official-app",
        "member",
        "member-openid",
    )
    assert await service.links_for(_onebot()) == (link,)
    assert await service.links_for(_official_member()) == (link,)

    with sqlite3.connect(path) as connection:
        stored_hash = str(
            connection.execute(
                "SELECT token_hash FROM identity_link_challenges"
            ).fetchone()[0]
        )
        audit_actions = tuple(
            row[0]
            for row in connection.execute(
                "SELECT action FROM identity_link_audit ORDER BY id"
            ).fetchall()
        )
    assert challenge.token not in stored_hash
    assert len(stored_hash) == 64
    assert audit_actions == ("issued", "linked")


@pytest.mark.asyncio
async def test_service_resolves_only_the_exact_linked_official_identity(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path / "state.sqlite")
    challenge = await service.begin(_onebot())
    await service.confirm(_official_member(), challenge.token)

    assert await service.linked_onebot_actor(_official_member()) == _onebot()
    assert await service.linked_onebot_actor(_onebot()) == _onebot()
    assert await service.linked_onebot_actor(_official_user()) is None
    assert (
        await service.linked_onebot_actor(_official_member(group_id="another-group"))
        == _onebot()
    )


@pytest.mark.asyncio
async def test_service_requires_explicit_account_when_multiple_are_enabled(
    tmp_path: Path,
) -> None:
    service = _service(
        tmp_path / "state.sqlite",
        accounts={
            "main": OfficialAccount("main", "app-main"),
            "test": OfficialAccount("test", "app-test"),
        },
    )

    with pytest.raises(IdentityLinkingAccountError, match="main、test"):
        await service.begin(_onebot())

    challenge = await service.begin(_onebot(), "TEST")
    assert challenge.account == OfficialAccount("test", "app-test")


def test_service_rejects_app_ids_that_collide_after_normalization(
    tmp_path: Path,
) -> None:
    with pytest.raises(IdentityLinkingError, match="AppIDs must be unique"):
        _service(
            tmp_path / "state.sqlite",
            accounts={
                "main": OfficialAccount("main", "official-app"),
                "duplicate": OfficialAccount("duplicate", " official-app "),
            },
        )


def test_service_rejects_aliases_that_collide_after_normalization(
    tmp_path: Path,
) -> None:
    with pytest.raises(IdentityLinkingError, match="unique after normalization"):
        _service(
            tmp_path / "state.sqlite",
            accounts={
                "Main": OfficialAccount("main", "app-main"),
                "main": OfficialAccount("MAIN", "app-duplicate"),
            },
        )


@pytest.mark.asyncio
async def test_service_rejects_wrong_platforms_and_non_numeric_onebot_id(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path / "state.sqlite")

    with pytest.raises(IdentityLinkingPlatformError):
        await service.begin(_official_user())
    with pytest.raises(IdentityLinkingPlatformError):
        await service.begin(_onebot("opaque"))
    with pytest.raises(IdentityLinkingPlatformError):
        await service.confirm(_onebot(), "2345-6789")


@pytest.mark.asyncio
async def test_challenge_is_scoped_expires_and_is_single_use(tmp_path: Path) -> None:
    now = [100.0]
    service = _service(tmp_path / "state.sqlite", now=now)
    challenge = await service.begin(_onebot())

    with pytest.raises(IdentityLinkingTokenError, match="不属于"):
        await service.confirm(
            _official_member(app_id="another-app"),
            challenge.token,
        )

    now[0] = 161.0
    with pytest.raises(IdentityLinkingTokenError, match="已过期"):
        await service.confirm(_official_member(), challenge.token)

    now[0] = 200.0
    replacement = await service.begin(_onebot())
    await service.confirm(_official_member(), replacement.token)
    with pytest.raises(IdentityLinkingTokenError, match="已使用"):
        await service.confirm(_official_member(), replacement.token)


@pytest.mark.asyncio
async def test_onebot_can_link_distinct_member_and_user_openids(tmp_path: Path) -> None:
    service = _service(tmp_path / "state.sqlite")

    first = await service.begin(_onebot())
    await service.confirm(_official_member(), first.token)
    second = await service.begin(_onebot())
    await service.confirm(_official_user(), second.token)

    links = await service.links_for(_onebot())
    assert {link.official.kind for link in links} == {"member", "user"}
    assert {link.official.openid for link in links} == {
        "member-openid",
        "user-openid",
    }


@pytest.mark.asyncio
async def test_existing_official_identity_cannot_be_reassigned(tmp_path: Path) -> None:
    service = _service(tmp_path / "state.sqlite")
    first = await service.begin(_onebot("10001"))
    await service.confirm(_official_member(), first.token)
    second = await service.begin(_onebot("10002"))

    with pytest.raises(IdentityLinkingConflictError):
        await service.confirm(_official_member(), second.token)


@pytest.mark.asyncio
async def test_revoke_works_from_either_platform_and_records_audit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite"
    service = _service(path)
    first = await service.begin(_onebot())
    await service.confirm(_official_member(), first.token)
    second = await service.begin(_onebot())
    await service.confirm(_official_user(), second.token)

    assert await service.revoke(_official_member()) == 1
    assert len(await service.links_for(_onebot())) == 1
    assert await service.revoke(_onebot()) == 1
    assert await service.links_for(_onebot()) == ()

    with sqlite3.connect(path) as connection:
        revoked = connection.execute(
            "SELECT COUNT(*) FROM identity_link_audit WHERE action = 'revoked'"
        ).fetchone()[0]
    assert revoked == 2


@pytest.mark.asyncio
async def test_store_allows_only_one_concurrent_consumer(tmp_path: Path) -> None:
    store = _store(tmp_path / "state.sqlite")
    await store.issue(
        token_hash="token-hash",
        onebot_qq_id="10001",
        official_app_id="official-app",
        created_at=100.0,
        expires_at=200.0,
    )
    official = OfficialIdentity(
        "official-app",
        "member",
        "member-openid",
        "group-openid",
    )

    results = await asyncio.gather(
        *(
            store.consume(token_hash="token-hash", official=official, now=101.0)
            for _ in range(8)
        ),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert (
        sum(isinstance(result, IdentityLinkChallengeInvalidError) for result in results)
        == 7
    )


@pytest.mark.asyncio
async def test_store_reports_conflicting_owner_without_consuming_token(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "state.sqlite")
    official = OfficialIdentity(
        "official-app",
        "user",
        "user-openid",
    )
    await store.issue(
        token_hash="first",
        onebot_qq_id="10001",
        official_app_id="official-app",
        created_at=100.0,
        expires_at=200.0,
    )
    await store.consume(token_hash="first", official=official, now=101.0)
    await store.issue(
        token_hash="second",
        onebot_qq_id="10002",
        official_app_id="official-app",
        created_at=102.0,
        expires_at=200.0,
    )

    with pytest.raises(IdentityLinkConflictError) as raised:
        await store.consume(token_hash="second", official=official, now=103.0)

    assert raised.value.existing_qq_id == "10001"


@pytest.mark.asyncio
async def test_shared_commands_complete_status_and_revoke_flow(tmp_path: Path) -> None:
    commands = IdentityLinkCommands(_service(tmp_path / "state.sqlite"))
    onebot_context = _context(_onebot(), "关联官方账号")

    issued = await commands.begin_text("关联官方账号", onebot_context)
    token = issued.splitlines()[0].split("：", 1)[1]
    assert token not in repr(commands.service.store)

    official_context = _context(_official_member(), f"关联账号 {token}")
    confirmed = await commands.portable_confirm(
        official_context.text,
        official_context,
    )
    assert _outbound_text(confirmed) == (
        "账号关联成功。现在两个接入端会识别为同一位用户。"
    )
    official_status = await commands.portable_status("账号关联", official_context)
    assert "******2661" in _outbound_text(official_status)

    onebot_status = await commands.status_text(onebot_context)
    assert "official-app / 群成员 / memb...enid" in onebot_status
    revoked = await commands.portable_revoke("解除账号关联", official_context)
    assert _outbound_text(revoked) == "已解除 1 条跨平台账号关联。"
    assert await commands.status_text(onebot_context) == (
        "当前账号尚未建立跨平台关联。"
    )
