# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolve player-query targets from references, bindings, or one @ member."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from ironsbot.core.commands import normalize_command_text
from ironsbot.runtime.message_input import message_input_context
from ironsbot.runtime.onebot_context import event_group_id
from ironsbot.services.seer.ids import PLAYER_ID_ERROR_MESSAGE, is_valid_player_id
from ironsbot.services.seer.player_messages import unbound_player_shortcut_message

if TYPE_CHECKING:
    from collections.abc import Callable

    from nonebot.adapters import Event

    from ironsbot.config.player_accounts import PlayerAccount, PlayerAccountRegistry


@dataclass(frozen=True, slots=True)
class PlayerTargetChoice:
    """One visible configured account offered after a partial alias match."""

    player_id: int
    display: str


@dataclass(frozen=True, slots=True)
class PlayerTargetResolution:
    player_id: int | None
    offer_binding: bool
    error: str | None = None
    recognized: bool = True
    choices: tuple[PlayerTargetChoice, ...] = ()


def default_player_id_for(service: object, user_id: int) -> int | None:
    """Read a default binding without coupling target parsing to PlayerService."""

    lookup = getattr(service, "default_player_id", None)
    player_id = lookup(user_id) if callable(lookup) else None
    return player_id if isinstance(player_id, int) else None


def allows_private_player_aliases(features: object, user_id: int) -> bool:
    """Return whether this event user may resolve private configured aliases."""

    is_superuser = getattr(features, "is_superuser", None)
    return bool(is_superuser(user_id)) if callable(is_superuser) else False


def resolve_event_player_reference(
    accounts: PlayerAccountRegistry,
    event: Event,
    reference: object,
    *,
    allow_private: bool = False,
) -> int | None:
    """Resolve one numeric or configured player reference in event scope."""

    return accounts.resolve_player_id(
        reference,
        group_id=event_group_id(event) if isinstance(event, MessageEvent) else None,
        allow_private=allow_private,
    )


def resolve_event_player_target(  # noqa: C901, PLR0913 - event resolution inputs are explicit
    accounts: PlayerAccountRegistry,
    event: Event,
    reference: str | None,
    *,
    binding_for_user: Callable[[int], int | None],
    allow_private: bool = False,
    allow_default: bool = True,
    allow_partial_reference: bool = False,
) -> PlayerTargetResolution:
    """Resolve one current-message player target under all public query rules."""

    if not isinstance(event, MessageEvent):
        return PlayerTargetResolution(None, offer_binding=False, recognized=False)
    normalized = "" if reference is None else reference.strip()
    explicit_player_id: int | None = None
    if normalized:
        if normalized.isdecimal():
            explicit_player_id = int(normalized)
            if not is_valid_player_id(explicit_player_id):
                return PlayerTargetResolution(
                    None,
                    offer_binding=False,
                    error=PLAYER_ID_ERROR_MESSAGE,
                )
        else:
            explicit_player_id = resolve_event_player_reference(
                accounts,
                event,
                normalized,
                allow_private=allow_private,
            )
            if explicit_player_id is None:
                choices = (
                    _player_target_choices(
                        accounts.find_player_accounts(
                            normalized,
                            group_id=event_group_id(event),
                            allow_private=allow_private,
                        ),
                        normalized,
                    )
                    if allow_partial_reference
                    else ()
                )
                if len(choices) == 1:
                    explicit_player_id = choices[0].player_id
                elif choices:
                    return PlayerTargetResolution(
                        None,
                        offer_binding=False,
                        choices=choices,
                    )
            if explicit_player_id is None:
                return PlayerTargetResolution(
                    None,
                    offer_binding=False,
                    recognized=False,
                )

    if explicit_player_id is None and not allow_default:
        context = message_input_context(event)
        if not context.has_member_mentions:
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                recognized=False,
            )

    return resolve_player_target(
        event,
        numeric_player_id=explicit_player_id,
        binding_for_user=binding_for_user,
    )


def _player_target_choices(
    accounts: tuple[PlayerAccount, ...],
    reference: str,
) -> tuple[PlayerTargetChoice, ...]:
    return tuple(
        PlayerTargetChoice(
            player_id=account.player_id,
            display=f"{_matching_reference(account, reference)}（{account.player_id}）",
        )
        for account in accounts
    )


def _matching_reference(account: PlayerAccount, reference: str) -> str:
    normalized = normalize_command_text(reference)
    return next(
        (
            value
            for value in (account.name, *account.aliases)
            if normalized in normalize_command_text(value)
        ),
        account.name,
    )


def resolve_player_target(  # noqa: PLR0911
    event: MessageEvent,
    *,
    numeric_player_id: int | None,
    binding_for_user: Callable[[int], int | None],
) -> PlayerTargetResolution:
    """Use exactly one current-message @ target, never a quoted message body."""

    context = message_input_context(event)
    if context.has_member_mentions:
        if not isinstance(event, GroupMessageEvent):
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                error="私聊不能使用 @成员 查询米米号。",
            )
        if numeric_player_id is not None:
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                error="米米号或玩家别名和 @成员 不能同时使用，请保留其中一种。",
            )
        if len(context.member_user_ids) != 1:
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                error="请一次只 @ 一名成员查询其已绑定的米米号。",
            )
        if binding_for_user(event.user_id) is None:
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                error=unbound_player_shortcut_message(),
            )
        player_id = binding_for_user(context.member_user_ids[0])
        if player_id is None:
            return PlayerTargetResolution(
                None,
                offer_binding=False,
                error="该成员尚未绑定米米号。",
            )
        return PlayerTargetResolution(player_id, offer_binding=False)

    if numeric_player_id is not None:
        return PlayerTargetResolution(numeric_player_id, offer_binding=True)
    return PlayerTargetResolution(
        binding_for_user(event.user_id),
        offer_binding=False,
    )
