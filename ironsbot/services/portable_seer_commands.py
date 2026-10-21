# SPDX-License-Identifier: MIT
"""Build platform-neutral operations for core Seer queries."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_data_commands import build_portable_data_operation
from ironsbot.services.portable_query_operations import build_query_operation
from ironsbot.services.portable_query_sessions import QueryOperationSpec
from ironsbot.services.portable_reply import PortableReply, slow_operation_reply
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.peak import (
    PEAK_EXPERT_POOL_COMMANDS,
    PEAK_MASTER_POOL_COMMANDS,
    PEAK_PET_RANK_COMMANDS,
    PEAK_POOL_COMMANDS,
    PEAK_SUIT_RANK_COMMANDS,
    PEAK_TITLE_RANK_COMMANDS,
    PEAK_VOTE_COMMANDS,
)
from ironsbot.services.seer.query_commands import (
    BATTLE_EFFECT_QUERY,
    EQUIP_QUERY,
    GEM_QUERY,
    MINTMARK_QUERY,
    SUIT_QUERY,
    TITLE_QUERY,
    TYPE_QUERY,
    pet_avatar_input,
    pet_image_input,
    pet_query_input,
)
from ironsbot.services.seer.rank_help import format_rank_help
from ironsbot.services.seer.team_commands import build_team_query_operation

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from ironsbot.core.affix_commands import AffixCommand
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.equipment import EquipmentKind
    from ironsbot.services.seer.peak import PeakQueryResult, PeakQueryService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.resources import SeerQueryResources


def build_portable_rank_help_operation(
    catalog: CommandCatalog, features: FeatureService
) -> PortableOperation:
    async def rank_help_message(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        command_help = catalog.format_for_context(
            _command_context(context),
            features,
            plugin_id="rank_help",
        )
        return OutboundMessage.from_text(
            f"📊【可用榜单】\n{format_rank_help(command_help)}"
        )

    return rank_help_message


def build_portable_seer_operations(
    catalog: CommandCatalog,
    seer: SeerQueryResources,
    sessions: PortableQuerySessions,
    features: FeatureService,
    player_id_resolver: PlayerIdResolver,
) -> dict[str, PortableOperation]:
    """Build core Seer operations from existing parsers and domain services."""

    data_query = build_portable_data_operation(
        seer.data_queries, seer.external_references
    )

    operations: dict[str, PortableOperation] = {
        "seer.data.query": data_query,
        "seer.team.query": build_team_query_operation(
            seer.team_query,
            player_id_resolver,
            features,
            sessions,
        ),
        "rank.help": build_portable_rank_help_operation(catalog, features),
        "seer.peak.query": build_peak_query_operation(seer.peak_query),
        "seer.peak.rank": build_peak_rank_operation(seer.peak_query),
        **build_portable_catalog_queries(seer, sessions),
    }
    if seer.pet_flip is not None:
        operations["seer.pet.flip"] = seer.pet_flip.play
    if "seer.pet.avatar" not in catalog.command_ids:
        operations.pop("seer.pet.avatar", None)
    return operations


def build_portable_catalog_queries(
    seer: SeerQueryResources, sessions: PortableQuerySessions
) -> dict[str, PortableOperation]:
    """One definition of resource searches, menu labels and selection callbacks."""
    operations: dict[str, PortableOperation] = {
        "seer.pet.query": build_query_operation(
            sessions,
            QueryOperationSpec(
                parser=pet_query_input().parse_argument,
                search=seer.pet_query.search_info,
                select=seer.pet_query.select_info,
                contextual_search=lambda arg, ctx: seer.pet_query.search_info(
                    arg, execution_identity=ctx.execution_identity
                ),
                contextual_select=lambda value, ctx: seer.pet_query.select_info(
                    value, execution_identity=ctx.execution_identity
                ),
                prompt_title="请问你想查询的精灵是……",
            ),
        ),
        "seer.pet.image": build_query_operation(
            sessions,
            QueryOperationSpec(
                parser=pet_image_input().parse_argument,
                search=seer.pet_query.search_image,
                select=seer.pet_query.select_image,
                prompt_title="请问你想查询的立绘是……",
            ),
        ),
        "seer.mintmark.query": _first_matching_operation(
            (
                (
                    MINTMARK_QUERY,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=MINTMARK_QUERY.parse_argument,
                            search=seer.mintmark.search_mintmark,
                            select=seer.mintmark.select_mintmark,
                            prompt_title="请问你想查询的刻印是……",
                        ),
                    ),
                ),
                (
                    GEM_QUERY,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=GEM_QUERY.parse_argument,
                            search=seer.mintmark.search_gem,
                            select=seer.mintmark.select_gem,
                            prompt_title="请问你想查询的宝石是……",
                        ),
                    ),
                ),
            )
        ),
        "seer.equipment.query": _first_matching_operation(
            tuple(
                (
                    parser,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=parser.parse_argument,
                            search=partial(seer.equipment.search, kind),
                            select=partial(seer.equipment.select, kind),
                            prompt_title=prompt_title,
                        ),
                    ),
                )
                for kind, parser, prompt_title in _equipment_queries()
            )
        ),
        "seer.type.query": _first_matching_operation(
            (
                (
                    TYPE_QUERY,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=TYPE_QUERY.parse_argument,
                            search=seer.type_query.search,
                            select=seer.type_query.select,
                            prompt_title="请问你想查询的属性是……",
                        ),
                    ),
                ),
                (
                    BATTLE_EFFECT_QUERY,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=BATTLE_EFFECT_QUERY.parse_argument,
                            search=seer.battle_effect.search,
                            select=seer.battle_effect.select,
                            prompt_title="请问你想查询的异常状态是……",
                        ),
                    ),
                ),
            )
        ),
    }
    operations["seer.pet.avatar"] = build_query_operation(
        sessions,
        QueryOperationSpec(
            parser=pet_avatar_input().parse_argument,
            search=seer.pet_query.search_avatar,
            select=seer.pet_query.select_avatar,
            prompt_title="请选择要查询头像的精灵或皮肤：",
        ),
    )
    return operations


def _equipment_queries() -> tuple[tuple[EquipmentKind, AffixCommand, str], ...]:
    return (
        ("suit", SUIT_QUERY, "请问你想查询的套装是……"),
        (
            "equip",
            EQUIP_QUERY,
            "请问你想查询的装备部件是……",
        ),
        (
            "title",
            TITLE_QUERY,
            "请问你想查询的称号是……",
        ),
    )


def _first_matching_operation(
    routes: tuple[tuple[AffixCommand, PortableOperation], ...],
) -> PortableOperation:
    async def execute(text: str, context: MessageInputContext):
        operation = next(
            (operation for parser, operation in routes if parser(text) is not None),
            None,
        )
        if operation is None:
            msg = f"catalog accepted input that no portable operation owns: {text!r}"
            raise ValueError(msg)
        return await operation(text, context)

    return execute


def _command_context(context: MessageInputContext) -> CommandContext:
    message = context.message
    return CommandContext(
        actor=message.actor,
        conversation=message.conversation,
        group_role=message.group_role,
        member_mentions=message.direct_mentions,
    )


async def _ignore_progress(_message: str) -> None:
    """Stage updates are replaced by a single delayed waiting notice."""


async def _peak_result(operation: Awaitable[PeakQueryResult]) -> OutboundMessage:
    try:
        result = await operation
    except DataUnavailableError:
        return OutboundMessage.from_text(
            DATABASE_UNAVAILABLE_MESSAGE, request_succeeded=False
        )
    return result.to_outbound()


def build_peak_query_operation(service: PeakQueryService) -> PortableOperation:
    async def query(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del context
        if text in PEAK_POOL_COMMANDS:
            operation = service.pool(expert=False, progress=_ignore_progress)
        elif text in PEAK_EXPERT_POOL_COMMANDS:
            operation = service.pool(expert=True, progress=_ignore_progress)
        elif text in PEAK_MASTER_POOL_COMMANDS:
            operation = service.master_pool(_ignore_progress)
        elif text in PEAK_VOTE_COMMANDS:
            operation = service.vote(_ignore_progress)
        else:
            msg = f"unsupported portable peak query command: {text!r}"
            raise ValueError(msg)
        return await _peak_result(operation)

    async def execute(text: str, context: MessageInputContext) -> PortableReply:
        return await slow_operation_reply(query(text, context))

    return execute


def build_peak_rank_operation(service: PeakQueryService) -> PortableOperation:
    async def query(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del context
        if text in PEAK_SUIT_RANK_COMMANDS:
            operation = service.item_rank(text, kind="套装")
        elif text in PEAK_TITLE_RANK_COMMANDS:
            operation = service.item_rank(text, kind="称号")
        elif text in PEAK_PET_RANK_COMMANDS:
            operation = service.pet_rank(text, _ignore_progress)
        else:
            msg = f"unsupported portable peak rank command: {text!r}"
            raise ValueError(msg)
        return await _peak_result(operation)

    async def execute(text: str, context: MessageInputContext) -> PortableReply:
        return await slow_operation_reply(query(text, context))

    return execute
