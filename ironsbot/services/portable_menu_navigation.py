# SPDX-License-Identifier: MIT
"""Parent menu snapshots shared by every transport, without rerunning queries."""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.services.portable_session_state import _MENU_ACCESS

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_query_types import (
        _PendingSelection,
        _PendingTextInput,
    )
    from ironsbot.services.portable_reply import PortableReply

_ACTIVE_MENU: ContextVar[_PendingSelection | None] = ContextVar(
    "active_parent_menu", default=None
)
_EXIT_LINE = re.compile(r"(?m)^(\s*0[.、．]\s*)【退出】")


@contextmanager
def selecting_menu(pending: _PendingSelection | None) -> Iterator[None]:
    token = _ACTIVE_MENU.set(pending)
    try:
        yield
    finally:
        _ACTIVE_MENU.reset(token)


def active_menu() -> _PendingSelection | None:
    return _ACTIVE_MENU.get()


def menu_parent(*, child: bool) -> _PendingSelection | None:
    previous = active_menu()
    return previous if child else previous.parent if previous else None


def bind_navigation(reply: PortableReply, pending: _PendingSelection) -> PortableReply:
    """Retain the selecting frame while a deferred operation builds a child."""

    async def follow_up() -> OutboundMessage:
        assert reply.follow_up is not None
        with selecting_menu(pending):
            return await reply.follow_up()

    async def continuation() -> PortableReply | None:
        assert reply.continuation is not None
        with selecting_menu(pending):
            result = await reply.continuation()
        return bind_navigation(result, pending) if result is not None else None

    return replace(
        reply,
        follow_up=follow_up if reply.follow_up else None,
        continuation=continuation if reply.continuation else None,
    )


def install_navigation(
    sessions: PortableQuerySessions,
    context: MessageInputContext,
    pending: _PendingSelection,
    message: OutboundMessage,
    *,
    child: bool,
) -> OutboundMessage:
    parent = menu_parent(child=child)
    label = pending.exit_label or ("返回上级" if parent is not None else "退出")
    session = replace(
        pending.session,
        choices=tuple(
            replace(choice, label=label) if choice.id == "0" else choice
            for choice in pending.session.choices
        ),
    )
    parts = tuple(
        replace(
            part,
            text=_EXIT_LINE.sub(lambda match: match[1] + f"【{label}】", part.text),
        )
        if isinstance(part, TextPart)
        else part
        for part in message.parts
    )
    result = replace(message, parts=parts, prompt=session)
    sessions._pending[sessions._key(context)] = replace(
        pending,
        parent=parent,
        session=session,
        message=result,
    )
    return result


async def return_or_exit(
    sessions: PortableQuerySessions,
    context: MessageInputContext,
    pending: _PendingSelection | _PendingTextInput,
) -> OutboundMessage:
    parent = pending.parent
    sessions.discard(context)
    if parent is None:
        return OutboundMessage.from_text(pending.exit_message)
    if parent.access is not None and not parent.access(context):
        return OutboundMessage.from_text("当前会话没有使用上级菜单的权限。")
    session = sessions._new_session(
        context,
        tuple(choice for choice in parent.session.choices if choice.id != "0"),
    )
    restored = replace(
        parent,
        session=session,
        expires_at=session.expires_at,
        anchor_ids=frozenset(),
        prompt_content=None,
        owner_context=context,
    )
    if restored.refresh_on_return is not None:
        access_token = _MENU_ACCESS.set(restored.access)
        try:
            with (
                sessions.interactions.navigation_scope(context),
                selecting_menu(restored),
            ):
                return await restored.refresh_on_return(context)
        finally:
            _MENU_ACCESS.reset(access_token)
    if parent.message is None:
        return OutboundMessage.from_text("上级菜单已失效，请重新发送原指令。")
    with sessions.interactions.navigation_scope(context), selecting_menu(restored):
        return install_navigation(
            sessions, context, restored, parent.message, child=False
        )


def copy_shared_menu(
    sessions: PortableQuerySessions,
    pending: _PendingSelection,
    responder: MessageInputContext,
) -> _PendingSelection:
    choices = tuple(
        choice
        for choice in pending.session.choices
        if choice.id in pending.shared_choice_ids
    )
    ids = tuple(choice.id for choice in choices)
    session = sessions._new_session(responder, choices)
    filtered = set(ids) != set(pending.choice_ids)
    message = pending.message
    if filtered:
        message = OutboundMessage.from_text(
            "\n".join(
                (
                    pending.prompt_title or "请选择要查询的项目：",
                    *(
                        f"{choice.id}. {choice.label}"
                        for choice in choices
                        if choice.is_visible
                    ),
                    "0. 【退出】",
                )
            )
        )
    return replace(
        pending,
        session=session,
        choices=tuple(pending.choices[pending.choice_ids.index(key)] for key in ids),
        choice_ids=ids,
        select=pending.shared_select or pending.select,
        parent=None,
        message=message,
        shared_choice_ids=frozenset(ids),
        refresh_on_return=None if filtered else pending.refresh_on_return,
        anchor_ids=frozenset(),
        prompt_content=None,
        owner_context=responder,
        expires_at=session.expires_at,
        keep_open=True,
    )
