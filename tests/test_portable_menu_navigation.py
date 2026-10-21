from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, SendResult, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableQuerySessions,
)

MENU_TTL_SECONDS = 120


def context(
    platform: Platform, *, actor: str = "101", bot: str = "1"
) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            platform=platform,
            actor=ActorRef(platform, actor, account_id=bot),
            conversation=ConversationRef(platform, "group", "456", account_id=bot),
            message_id="request",
            text="menu",
        ),
        mentions_bot=True,
    )


def text(message: OutboundMessage) -> str:
    return "".join(part.text for part in message.parts if isinstance(part, TextPart))


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_delivery_starts_timer_and_back_renews_expired_parent(
    platform: Platform,
) -> None:
    now = 0.0
    sessions = PortableQuerySessions(now=lambda: now)
    ctx = context(platform)

    async def child(_value: str, current: MessageInputContext) -> OutboundMessage:
        return sessions.offer_menu(
            current,
            PortableMenuSpec(
                choices=("detail",),
                select=AsyncMock(),
                child=True,
                prompt=OutboundMessage.from_text("child"),
            ),
        )

    root = sessions.offer_menu(
        ctx,
        PortableMenuSpec(
            choices=("child",),
            select=child,
            prompt=OutboundMessage.from_text("root"),
        ),
    )
    now = 30
    sessions.record_delivery(ctx, root, SendResult(delivered=True, message_id="root"))
    active = sessions.active_prompt(ctx)
    assert active is not None and active.expires_at == now + MENU_TTL_SECONDS
    now = 140
    message = await sessions.select("1", ctx)
    assert isinstance(message, OutboundMessage)
    sessions.record_delivery(
        ctx, message, SendResult(delivered=True, message_id="child")
    )
    now = 200  # Parent's old deadline has passed, but its child is still active.
    restored = await sessions.select("0", ctx)
    assert isinstance(restored, OutboundMessage) and "root" in text(restored)
    sessions.record_delivery(
        ctx, restored, SendResult(delivered=True, message_id="back")
    )
    active = sessions.active_prompt(ctx)
    assert active is not None and active.expires_at == now + MENU_TTL_SECONDS
    assert sessions.menu_anchor(ctx) == "back"


@pytest.mark.asyncio
async def test_invalid_selection_does_not_renew_waiting_time() -> None:
    now = 0.0
    sessions = PortableQuerySessions(now=lambda: now)
    ctx = context(Platform.ONEBOT)
    message = sessions.offer_menu(
        ctx,
        PortableMenuSpec(
            choices=("item",),
            select=AsyncMock(return_value=OutboundMessage.from_text("done")),
            prompt=OutboundMessage.from_text("root"),
            keep_open=True,
        ),
    )
    sessions.record_delivery(
        ctx, message, SendResult(delivered=True, message_id="root")
    )
    now = 100
    await sessions.interactions.select("99", ctx)
    active = sessions.active_prompt(ctx)
    assert active is not None and active.expires_at == MENU_TTL_SECONDS
    now = 110
    await sessions.interactions.select("1", ctx)
    active = sessions.active_prompt(ctx)
    assert active is not None and active.expires_at == now + MENU_TTL_SECONDS


@pytest.mark.asyncio
async def test_accepted_slow_request_survives_menu_timeout() -> None:
    now = 0.0
    sessions = PortableQuerySessions(now=lambda: now)
    ctx = context(Platform.ONEBOT)
    entered, release = asyncio.Event(), asyncio.Event()

    async def operation(text: str, context: MessageInputContext) -> OutboundMessage:
        del text, context
        entered.set()
        await release.wait()
        return OutboundMessage.from_text("completed")

    task = asyncio.create_task(sessions.interactions.execute(operation, "query", ctx))
    await entered.wait()
    now = 500
    # Another user's operation causes idle generation cleanup.
    other = context(Platform.ONEBOT, actor="102")
    with sessions.interactions.navigation_scope(other):
        pass
    release.set()
    reply = await task
    assert reply is not None and reply.is_current is not None and reply.is_current()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_nested_back_restores_snapshots_and_replaces_anchor(
    platform: Platform,
) -> None:
    sessions = PortableQuerySessions()
    ctx = context(platform)
    called = AsyncMock()

    async def leaf(_value: str, current: MessageInputContext) -> OutboundMessage:
        await called()
        return sessions.offer_view(
            current, OutboundMessage.from_text("detail\n0.【退出】")
        )

    async def child(_value: str, current: MessageInputContext) -> OutboundMessage:
        return sessions.offer_menu(
            current,
            PortableMenuSpec(
                choices=("detail",),
                select=leaf,
                child=True,
                prompt=OutboundMessage.from_text("child\n0.【退出】"),
            ),
        )

    root = sessions.offer_menu(
        ctx,
        PortableMenuSpec(
            choices=("child",),
            select=child,
            prompt=OutboundMessage.from_text("root\n0.【退出】"),
        ),
    )
    sessions.record_delivery(ctx, root, SendResult(delivered=True, message_id="root"))
    child_message = await sessions.select("1", ctx)
    assert child_message is not None and "返回上级" in text(child_message)
    leaf_message = await sessions.select("1", ctx)
    assert leaf_message is not None and "返回上级" in text(leaf_message)
    back_child = await sessions.select("0", ctx)
    assert back_child is not None and text(back_child) == text(child_message)
    assert back_child.prompt is not None and child_message.prompt is not None
    assert back_child.prompt.id != child_message.prompt.id
    sessions.record_delivery(
        ctx, back_child, SendResult(delivered=True, message_id="restored")
    )
    stale = replace(ctx, message=replace(ctx.message, reply_to_id="root"))
    assert await sessions.select("1", stale) is None
    back_root = await sessions.select("0", ctx)
    assert back_root is not None and "root" in text(back_root)
    assert back_root.prompt is not None and root.prompt is not None
    assert back_root.prompt.id != root.prompt.id
    called.assert_awaited_once()
    exit_message = await sessions.select("0", ctx)
    assert exit_message is not None and "退出" in text(exit_message)
    assert not sessions.has_active_session(ctx)


@pytest.mark.asyncio
async def test_same_level_refresh_does_not_grow_back_stack() -> None:
    sessions = PortableQuerySessions()
    ctx = context(Platform.QQ_OFFICIAL)

    async def refresh(_value: str, current: MessageInputContext) -> OutboundMessage:
        return menu(current)

    def menu(current: MessageInputContext, *, child: bool = False) -> OutboundMessage:
        return sessions.offer_menu(
            current,
            PortableMenuSpec(
                choices=("toggle",),
                select=refresh,
                child=child,
                prompt=OutboundMessage.from_text("settings\n0.【退出】"),
            ),
        )

    async def enter(_value: str, current: MessageInputContext) -> OutboundMessage:
        return menu(current, child=True)

    sessions.offer_menu(
        ctx,
        PortableMenuSpec(
            choices=("settings",),
            select=enter,
            prompt=OutboundMessage.from_text("root"),
        ),
    )
    await sessions.select("1", ctx)
    await sessions.select("1", ctx)
    await sessions.select("1", ctx)
    restored = await sessions.select("0", ctx)
    assert restored is not None and text(restored) == "root"


@pytest.mark.asyncio
async def test_back_rechecks_access_and_failed_delivery_cleans_navigation() -> None:
    sessions = PortableQuerySessions()
    ctx = context(Platform.QQ_OFFICIAL)
    allowed = True

    async def enter(_value: str, current: MessageInputContext) -> OutboundMessage:
        return sessions.offer_view(current, OutboundMessage.from_text("detail"))

    def root() -> OutboundMessage:
        return sessions.offer_menu(
            ctx,
            PortableMenuSpec(
                choices=("child",),
                select=enter,
                access=lambda _: allowed,
                prompt=OutboundMessage.from_text("root"),
            ),
        )

    root()
    await sessions.select("1", ctx)
    allowed = False
    denied = await sessions.select("0", ctx)
    assert denied is not None and "权限" in text(denied)
    assert not sessions.has_active_session(ctx)
    allowed = True
    root()
    await sessions.select("1", ctx)
    restored = await sessions.select("0", ctx)
    assert restored is not None
    sessions.record_delivery(
        ctx, restored, SendResult(delivered=False, error_message="test failure")
    )
    assert not sessions.has_active_session(ctx)


@pytest.mark.asyncio
@pytest.mark.parametrize("button", [False, True])
async def test_late_child_cannot_overwrite_back_navigation(*, button: bool) -> None:
    sessions = PortableQuerySessions()
    ctx = context(Platform.QQ_OFFICIAL)
    started = asyncio.Event()
    finish = asyncio.Event()

    async def slow(_value: str, current: MessageInputContext) -> OutboundMessage:
        started.set()
        await finish.wait()
        return sessions.offer_view(current, OutboundMessage.from_text("late"))

    async def enter(_value: str, current: MessageInputContext) -> OutboundMessage:
        return sessions.offer_menu(
            current,
            PortableMenuSpec(
                choices=("slow",),
                select=slow,
                child=True,
                keep_open=True,
                prompt=OutboundMessage.from_text("child"),
            ),
        )

    sessions.offer_menu(
        ctx,
        PortableMenuSpec(
            choices=("child",),
            select=enter,
            prompt=OutboundMessage.from_text("root"),
        ),
    )
    await sessions.select("1", ctx)
    task = asyncio.create_task(sessions.interactions.select("1", ctx))
    await started.wait()
    prompt = sessions.active_prompt(ctx)
    assert prompt is not None
    zero = prompt.action_data(prompt.choices[-1]) if button else "0"
    back = await sessions.interactions.select(zero, ctx)
    assert back is not None and text(back.message) == "root"
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sessions.active_prompt(ctx) == back.message.prompt
