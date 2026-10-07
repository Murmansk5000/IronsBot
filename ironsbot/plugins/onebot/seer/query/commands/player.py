# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING

from nonebot.adapters import Event  # noqa: TC002 - NoneBot resolves at runtime
from nonebot.adapters.onebot.v11 import MessageEvent, PrivateMessageEvent
from nonebot.matcher import Matcher  # noqa: TC002 - NoneBot resolves at runtime
from nonebot.rule import Rule

from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.player_reference_commands import player_reference_input_matcher
from ironsbot.integrations.onebot.matchers import CommandPolicy, bind_async
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.portable_queries import make_portable_query_handler
from ironsbot.integrations.onebot.replies import finish_event_reply
from ironsbot.integrations.onebot.rules import (
    affix_command,
    explicit_command,
    member_target_command,
)
from ironsbot.services.identity_link_commands import (
    IDENTITY_LINK_BEGIN,
    IdentityLinkCommands,
)
from ironsbot.services.portable_player_commands import build_portable_player_operations
from ironsbot.services.seer.player_query import (
    PLAYER_BINDING_PREFIX,
    PLAYER_QUERY_PREFIXES,
)

from ..group import SeerMatcherGroup, seer_feature_rule

if TYPE_CHECKING:
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver


async def _is_player_query_command(
    event: Event, *, resolver: PlayerIdResolver | None = None
) -> bool:
    if not isinstance(event, MessageEvent):
        return False
    context = message_input_context(event)
    return player_reference_input_matcher(
        PLAYER_QUERY_PREFIXES,
        resolver.has_reference_choices
        if resolver is not None
        else lambda *_: False,
    )(context.text, command_context_from_input(context))


async def _is_binding_command(
    event: Event, *, resolver: PlayerIdResolver | None = None
) -> bool:
    if not isinstance(event, MessageEvent):
        return False
    context = message_input_context(event)
    return player_reference_input_matcher(
        (PLAYER_BINDING_PREFIX,),
        resolver.has_reference_choices
        if resolver is not None
        else lambda *_: False,
    )(context.text, command_context_from_input(context))


async def _is_private_message(event: Event) -> bool:
    return isinstance(event, PrivateMessageEvent)


async def handle_identity_link_begin(
    identity_links: IdentityLinkCommands,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    context = message_input_context(event)
    await finish_event_reply(
        matcher,
        event,
        await identity_links.begin_text(event.get_plaintext(), context),
    )


async def handle_identity_link_status(
    identity_links: IdentityLinkCommands,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        await identity_links.status_text(message_input_context(event)),
    )


async def handle_identity_link_revoke(
    identity_links: IdentityLinkCommands,
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await finish_event_reply(
        matcher,
        event,
        await identity_links.revoke_text(message_input_context(event)),
    )


def _install_portable_matcher(
    group: SeerMatcherGroup,
    *,
    operation: PortableOperation,
    command_id: str,
    help_id: str,
    rule: Rule,
) -> None:
    matcher = group.on_message(
        policy=CommandPolicy.command(command_id, help_ids=(help_id,)),
        rule=seer_feature_rule(group.features, "seer_player") & rule,
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    matcher.append_handler(make_portable_query_handler(operation, group.query_sessions))


def install(group: SeerMatcherGroup) -> None:
    operations = build_portable_player_operations(
        group.resources.player,
        group.player_id_resolver,
        group.query_sessions,
        group.features,
        group.resources.player_detail_extensions,
        group.resources.rank_queries,
    )
    identity_begin_matcher = group.on_message(
        policy=CommandPolicy.command(
            "identity_link_begin",
            help_ids=("seer.player.identity.begin",),
        ),
        rule=seer_feature_rule(group.features, "seer_player")
        & affix_command(IDENTITY_LINK_BEGIN)
        & Rule(_is_private_message)
        & explicit_command(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    identity_begin_matcher.append_handler(
        bind_async(handle_identity_link_begin, group.identity_links)
    )

    identity_status_matcher = group.on_fullmatch(
        ("账号关联",),
        policy=CommandPolicy.command(
            "identity_link_status",
            help_ids=("seer.player.identity.status",),
        ),
        rule=seer_feature_rule(group.features, "seer_player") & explicit_command(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    identity_status_matcher.append_handler(
        bind_async(handle_identity_link_status, group.identity_links)
    )

    identity_revoke_matcher = group.on_fullmatch(
        ("解除账号关联",),
        policy=CommandPolicy.command(
            "identity_link_revoke",
            help_ids=("seer.player.identity.revoke",),
        ),
        rule=seer_feature_rule(group.features, "seer_player") & explicit_command(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    identity_revoke_matcher.append_handler(
        bind_async(handle_identity_link_revoke, group.identity_links)
    )

    _install_portable_matcher(
        group,
        operation=operations["seer.player.bind"],
        command_id="seer_player_binding",
        help_id="seer.player.bind",
        rule=Rule(bind_async(_is_binding_command, resolver=group.player_id_resolver))
        & member_target_command(),
    )
    unbind_matcher = group.on_fullmatch(
        ("解绑米米号",),
        policy=CommandPolicy.command(
            "seer_player_binding",
            help_ids=("seer.player.unbind",),
        ),
        rule=seer_feature_rule(group.features, "seer_player") & explicit_command(),
        priority=group.matcher_priority("seer_player"),
        block=True,
    )
    unbind_matcher.append_handler(
        make_portable_query_handler(
            operations["seer.player.unbind"],
            group.query_sessions,
        )
    )
    _install_portable_matcher(
        group,
        operation=operations["seer.player.query"],
        command_id="seer_player",
        help_id="seer.player.query",
        rule=Rule(
            bind_async(_is_player_query_command, resolver=group.player_id_resolver)
        ) & member_target_command(),
    )
