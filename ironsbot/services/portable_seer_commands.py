# SPDX-License-Identifier: MIT
"""Build platform-neutral operations for core Seer queries."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.commands import command_text_matches
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_query_sessions import (
    PortableQuerySessions,
    QueryOperationSpec,
    build_query_operation,
)
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
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
    from ironsbot.core.affix_commands import AffixParser
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.data_queries import DataQueryReply
    from ironsbot.services.seer.equipment import EquipmentKind
    from ironsbot.services.seer.peak import PeakQueryService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.resources import SeerQueryResources


def build_portable_seer_operations(
    catalog: CommandCatalog,
    seer: SeerQueryResources,
    sessions: PortableQuerySessions,
    features: FeatureService,
    player_id_resolver: PlayerIdResolver,
) -> dict[str, PortableOperation]:
    """Build core Seer operations from existing parsers and domain services."""

    async def data_query(
        text: str,
        context: MessageInputContext,
    ) -> DataQueryReply:
        del context
        if command_text_matches(text, DATA_VERSION_COMMANDS):
            return await seer.data_queries.data_version()
        if command_text_matches(text, SEASON_COUNTDOWN_COMMANDS):
            return await seer.data_queries.season_countdown()
        if command_text_matches(text, WEEKLY_PREVIEW_COMMANDS):
            return await seer.data_queries.weekly_preview()
        msg = f"unsupported portable Seer data command: {text!r}"
        raise ValueError(msg)

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

    operations: dict[str, PortableOperation] = {
        "seer.data.query": data_query,
        "seer.team.query": build_team_query_operation(
            seer.team_query,
            player_id_resolver,
            features,
        ),
        "rank.help": rank_help_message,
        "seer.peak.query": _build_peak_query_operation(seer.peak_query),
        "seer.peak.rank": _build_peak_rank_operation(seer.peak_query),
        "seer.pet.query": build_query_operation(
            sessions,
            QueryOperationSpec(
                parser=_affix_argument(pet_query_input()),
                search=seer.pet_query.search_info,
                select=seer.pet_query.select_info,
                prompt_title="请问你想查询的精灵是……",
                not_found_message="未找到对应精灵。",
            ),
        ),
        "seer.pet.image": build_query_operation(
            sessions,
            QueryOperationSpec(
                parser=_affix_argument(pet_image_input()),
                search=seer.pet_query.search_image,
                select=seer.pet_query.select_image,
                prompt_title="请问你想查询的立绘是……",
                not_found_message="未找到对应精灵或皮肤。",
            ),
        ),
        "seer.mintmark.query": _first_matching_operation(
            (
                (
                    MINTMARK_QUERY,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=_affix_argument(MINTMARK_QUERY),
                            search=seer.mintmark.search_mintmark,
                            select=seer.mintmark.select_mintmark,
                            prompt_title="请问你想查询的刻印是……",
                            not_found_message="未找到对应刻印。",
                        ),
                    ),
                ),
                (
                    GEM_QUERY,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=_affix_argument(GEM_QUERY),
                            search=seer.mintmark.search_gem,
                            select=seer.mintmark.select_gem,
                            prompt_title="请问你想查询的宝石是……",
                            not_found_message="未找到对应宝石。",
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
                            parser=_affix_argument(parser),
                            search=partial(seer.equipment.search, kind),
                            select=partial(seer.equipment.select, kind),
                            prompt_title=prompt_title,
                            not_found_message=not_found_message,
                        ),
                    ),
                )
                for kind, parser, prompt_title, not_found_message in (
                    _equipment_queries()
                )
            )
        ),
        "seer.type.query": _first_matching_operation(
            (
                (
                    TYPE_QUERY,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=_affix_argument(TYPE_QUERY),
                            search=seer.type_query.search,
                            select=seer.type_query.select,
                            prompt_title="请问你想查询的属性是……",
                            not_found_message="未找到对应属性。",
                        ),
                    ),
                ),
                (
                    BATTLE_EFFECT_QUERY,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=_affix_argument(BATTLE_EFFECT_QUERY),
                            search=seer.battle_effect.search,
                            select=seer.battle_effect.select,
                            prompt_title="请问你想查询的异常状态是……",
                            not_found_message="未找到对应异常状态。",
                        ),
                    ),
                ),
            )
        ),
    }
    if "seer.pet.avatar" in catalog.command_ids:
        operations["seer.pet.avatar"] = build_query_operation(
            sessions,
            QueryOperationSpec(
                parser=_affix_argument(pet_avatar_input()),
                search=seer.pet_query.search_avatar,
                select=seer.pet_query.select_avatar,
                prompt_title="请选择要查询头像的精灵：",
                not_found_message="未找到对应精灵。",
            ),
        )
    return operations


def _affix_argument(parser: AffixParser):
    def parse(text: str) -> str | None:
        parsed = parser(text)
        return None if parsed is None else parsed.argument

    return parse


def _equipment_queries() -> tuple[
    tuple[EquipmentKind, AffixParser, str, str], ...
]:
    return (
        ("suit", SUIT_QUERY, "请问你想查询的套装是……", "未找到对应套装。"),
        (
            "equip",
            EQUIP_QUERY,
            "请问你想查询的装备部件是……",
            "未找到对应装备部件。",
        ),
        (
            "title",
            TITLE_QUERY,
            "请问你想查询的称号是……",
            "未找到对应称号。",
        ),
    )


def _first_matching_operation(
    routes: tuple[tuple[AffixParser, PortableOperation], ...],
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
    """A passive platform sends only the final result for one command."""


def _build_peak_query_operation(service: PeakQueryService) -> PortableOperation:
    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del context
        if text in PEAK_POOL_COMMANDS:
            result = await service.pool(expert=False, progress=_ignore_progress)
        elif text in PEAK_EXPERT_POOL_COMMANDS:
            result = await service.pool(expert=True, progress=_ignore_progress)
        elif text in PEAK_MASTER_POOL_COMMANDS:
            result = await service.master_pool(_ignore_progress)
        elif text in PEAK_VOTE_COMMANDS:
            result = await service.vote(_ignore_progress)
        else:
            msg = f"unsupported portable peak query command: {text!r}"
            raise ValueError(msg)
        return result.to_outbound()

    return execute


def _build_peak_rank_operation(service: PeakQueryService) -> PortableOperation:
    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del context
        if text in PEAK_SUIT_RANK_COMMANDS:
            result = await service.item_rank(text, kind="套装")
        elif text in PEAK_TITLE_RANK_COMMANDS:
            result = await service.item_rank(text, kind="称号")
        elif text in PEAK_PET_RANK_COMMANDS:
            result = await service.pet_rank(text, _ignore_progress)
        else:
            msg = f"unsupported portable peak rank command: {text!r}"
            raise ValueError(msg)
        return result.to_outbound()

    return execute
