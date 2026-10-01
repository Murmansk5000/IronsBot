# SPDX-License-Identifier: MIT
"""Best-effort group and sender labels for command-triggered notices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from nonebot import get_bots

from ironsbot.core.platform import Platform, reference_digest

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.identity_principals import IdentityPrincipalService

_LOGGER = logging.getLogger(__name__)
_LOOKUP_TIMEOUT = 2.0
_MAX_LABEL_LENGTH = 80


def _label(value: object) -> str:
    return " ".join(str(value or "").split())[:_MAX_LABEL_LENGTH]


def _field(response: object, key: str) -> str:
    return _label(
        response.get(key)
        if isinstance(response, Mapping)
        else getattr(response, key, "")
    )


def _onebot_bots(preferred_id: str | None) -> tuple[Any, ...]:
    try:
        bots = get_bots()
    except Exception:  # noqa: BLE001 - notices do not require a live OneBot adapter
        return ()
    candidates = [bot for bot in bots.values() if hasattr(bot, "get_group_info")]
    candidates.sort(key=lambda bot: str(bot.self_id) != preferred_id)
    return tuple(candidates)


async def _group_name(bots: tuple[Any, ...], group_id: int) -> tuple[str, Any | None]:
    for bot in bots:
        try:
            response = await asyncio.wait_for(
                bot.get_group_info(group_id=group_id, no_cache=False),
                timeout=_LOOKUP_TIMEOUT,
            )
            return _field(response, "group_name"), bot
        except Exception:  # noqa: BLE001, PERF203 - try other connected bots
            continue
    return "", None


async def _user_name(
    bots: tuple[Any, ...],
    user_id: int,
    *,
    group_id: int | None,
    group_bot: Any | None,
) -> str:
    ordered = (group_bot, *(bot for bot in bots if bot is not group_bot))
    if group_id is not None:
        for bot in ordered:
            if bot is None:
                continue
            try:
                response = await asyncio.wait_for(
                    bot.get_group_member_info(
                        group_id=group_id, user_id=user_id, no_cache=False
                    ),
                    timeout=_LOOKUP_TIMEOUT,
                )
                name = _field(response, "nickname") or _field(response, "card")
                if name:
                    return name
            except Exception:  # noqa: BLE001 - try other connected bots
                continue
    for bot in ordered:
        if bot is None:
            continue
        try:
            response = await asyncio.wait_for(
                bot.get_stranger_info(user_id=user_id, no_cache=False),
                timeout=_LOOKUP_TIMEOUT,
            )
            if name := _field(response, "nickname"):
                return name
        except Exception:  # noqa: BLE001 - nickname is optional
            continue
    return ""


async def resolve_notice_origin(
    context: MessageInputContext,
    principals: IdentityPrincipalService,
) -> str:
    conversation = context.message.conversation
    actor = context.message.actor
    if conversation.platform is Platform.ONEBOT:
        group_id = conversation.id if conversation.kind == "group" else None
        qq_id = actor.id
    else:
        group = principals.conversation_principal(conversation)
        group_id = group.id if group.kind == "qq_group" else None
        linked_actor = principals.onebot_actor(actor)
        qq_id = linked_actor.id if linked_actor is not None else None

    preferred_id = (
        context.execution_identity.account_id
        if context.execution_identity is not None
        and context.execution_identity.platform is Platform.ONEBOT
        else None
    )
    bots = _onebot_bots(preferred_id)
    lines: list[str] = []
    group_bot = None
    if conversation.kind == "group":
        if group_id is None:
            lines.append(
                "群：QQ 群号未关联"
                f"（AppID：{conversation.account_id or '未知'}，"
                f"官方群标识：{reference_digest(conversation.id)}）"
            )
        else:
            try:
                group_name, group_bot = await _group_name(bots, int(group_id))
            except ValueError:
                _LOGGER.warning("invalid linked QQ group id in notice source")
                group_name = ""
            lines.append(
                f"群：{group_name}（QQ群：{group_id}）"
                if group_name
                else f"群：QQ群 {group_id}（名称暂不可用）"
            )
    else:
        lines.append("会话：私聊")

    name = _label(context.actor_display_name)
    if qq_id is not None and not name:
        try:
            name = await _user_name(
                bots,
                int(qq_id),
                group_id=int(group_id) if group_id is not None else None,
                group_bot=group_bot,
            )
        except ValueError:
            _LOGGER.warning("invalid linked QQ user id in notice source")
    if qq_id is not None:
        lines.append(f"用户：{name}（QQ：{qq_id}）" if name else f"用户：QQ {qq_id}")
    else:
        lines.append(
            f"用户：{name or 'QQ 号未关联'}"
            f"（AppID：{actor.account_id or '未知'}，"
            f"官方用户标识：{reference_digest(actor.id)}）"
        )
    return "\n".join(lines)
