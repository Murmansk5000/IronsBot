# SPDX-License-Identifier: MIT
"""Build platform-neutral operations for core Seer queries."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.authorization import can_manage_group_actor
from ironsbot.core.command_catalog import command_context_from_input
from ironsbot.core.commands import command_text_matches
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_query_sessions import (
    PortableQuerySessions,
    QueryOperationSpec,
    build_query_operation,
)
from ironsbot.services.portable_reply import (
    ProgressReporter,
    progress_operation_reply,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.external_references import SeerInfoReference
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
    pet_image_input,
    pet_query_input,
    team_player_query_reference,
    team_query_input,
)
from ironsbot.services.seer.rank_help import format_rank_help
from ironsbot.services.seer.team import TeamQueryActor

if TYPE_CHECKING:
    from ironsbot.core.affix_commands import AffixParser
    from ironsbot.core.command_catalog import CommandCatalog
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_reply import PortableOperation, PortableReply
    from ironsbot.services.seer.battle_effect import BattleEffectQueryService
    from ironsbot.services.seer.data_queries import SeerDataQueryService
    from ironsbot.services.seer.equipment import EquipmentKind, EquipmentQueryService
    from ironsbot.services.seer.external_references import SeerInfoReferences
    from ironsbot.services.seer.mintmark import MintmarkQueryService
    from ironsbot.services.seer.peak import PeakQueryService
    from ironsbot.services.seer.pet_query import PetQueryService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.resources import SeerQueryResources
    from ironsbot.services.seer.team import SeerTeamQueryService
    from ironsbot.services.seer.type_query import TypeQueryService


def build_portable_seer_operations(  # noqa: PLR0913 - explicit composition dependencies
    catalog: CommandCatalog,
    seer: SeerQueryResources,
    sessions: PortableQuerySessions,
    features: FeatureService,
    player_id_resolver: PlayerIdResolver,
    *,
    image_command_texts: frozenset[str] = frozenset(),
) -> dict[str, PortableOperation]:
    """Build core Seer operations from existing parsers and domain services."""

    return {
        "seer.data.query": build_portable_data_query_operation(
            seer.data_queries,
            getattr(seer, "external_references", None),
        ),
        "seer.team.query": build_portable_team_query_operation(
            seer.team_query,
            features,
            player_id_resolver,
        ),
        "rank.help": build_portable_rank_help_operation(catalog, features),
        "seer.peak.query": build_portable_peak_query_operation(seer.peak_query),
        "seer.peak.rank": build_portable_peak_rank_operation(seer.peak_query),
        **build_portable_pet_query_operations(
            seer.pet_query,
            sessions,
            image_command_texts=image_command_texts,
        ),
        **build_portable_mintmark_query_operations(seer.mintmark, sessions),
        **build_portable_equipment_query_operations(seer.equipment, sessions),
        **build_portable_type_query_operations(
            seer.type_query,
            seer.battle_effect,
            sessions,
        ),
    }


def build_portable_pet_query_operations(
    service: PetQueryService,
    sessions: PortableQuerySessions,
    *,
    image_command_texts: frozenset[str] = frozenset(),
) -> dict[str, PortableOperation]:
    return {
        "seer.pet.query": build_query_operation(
            sessions,
            QueryOperationSpec(
                parser=_affix_argument(pet_query_input(image_command_texts)),
                search=service.search_info,
                select=service.select_info,
                prompt_title="请问你想查询的精灵是……",
                not_found_message="未找到对应精灵。",
            ),
        ),
        "seer.pet.image": build_query_operation(
            sessions,
            QueryOperationSpec(
                parser=_affix_argument(pet_image_input(image_command_texts)),
                search=service.search_image,
                select=service.select_image,
                prompt_title="请问你想查询的立绘是……",
                not_found_message="未找到对应精灵或皮肤。",
            ),
        ),
    }


def build_portable_mintmark_query_operations(
    service: MintmarkQueryService,
    sessions: PortableQuerySessions,
) -> dict[str, PortableOperation]:
    return {
        "seer.mintmark.query": _first_matching_operation(
            (
                (
                    MINTMARK_QUERY,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=_affix_argument(MINTMARK_QUERY),
                            search=service.search_mintmark,
                            select=service.select_mintmark,
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
                            search=service.search_gem,
                            select=service.select_gem,
                            prompt_title="请问你想查询的宝石是……",
                            not_found_message="未找到对应宝石。",
                        ),
                    ),
                ),
            )
        )
    }


def build_portable_equipment_query_operations(
    service: EquipmentQueryService,
    sessions: PortableQuerySessions,
) -> dict[str, PortableOperation]:
    return {
        "seer.equipment.query": _first_matching_operation(
            tuple(
                (
                    parser,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=_affix_argument(parser),
                            search=partial(service.search, kind),
                            select=partial(service.select, kind),
                            prompt_title=prompt_title,
                            not_found_message=not_found_message,
                        ),
                    ),
                )
                for kind, parser, prompt_title, not_found_message in (
                    _equipment_queries()
                )
            )
        )
    }


def build_portable_type_query_operations(
    type_service: TypeQueryService,
    battle_effect_service: BattleEffectQueryService,
    sessions: PortableQuerySessions,
) -> dict[str, PortableOperation]:
    return {
        "seer.type.query": _first_matching_operation(
            (
                (
                    TYPE_QUERY,
                    build_query_operation(
                        sessions,
                        QueryOperationSpec(
                            parser=_affix_argument(TYPE_QUERY),
                            search=type_service.search,
                            select=type_service.select,
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
                            search=battle_effect_service.search,
                            select=battle_effect_service.select,
                            prompt_title="请问你想查询的异常状态是……",
                            not_found_message="未找到对应异常状态。",
                        ),
                    ),
                ),
            )
        )
    }


def build_portable_data_query_operation(
    service: SeerDataQueryService,
    references: SeerInfoReferences | None,
) -> PortableOperation:
    """Build shared data-version, season, and weekly-preview execution."""

    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del context
        reference: SeerInfoReference | None = None
        try:
            if command_text_matches(text, DATA_VERSION_COMMANDS):
                result = await service.data_version()
            elif command_text_matches(text, SEASON_COUNTDOWN_COMMANDS):
                result = await service.season_countdown()
            elif command_text_matches(text, WEEKLY_PREVIEW_COMMANDS):
                result = await service.weekly_preview()
                reference = SeerInfoReference.WEEKLY_PREVIEW
            else:
                msg = f"unsupported portable Seer data command: {text!r}"
                raise ValueError(msg)
        except DataUnavailableError:
            return OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
        if not isinstance(result, DataQueryImageReply):
            return OutboundMessage.from_text(result)
        reference_url = None if references is None else references.url_for(reference)
        return result.to_outbound(reference_url=reference_url)

    return execute


def build_portable_team_query_operation(
    service: SeerTeamQueryService,
    features: FeatureService,
    resolver: PlayerIdResolver,
) -> PortableOperation:
    """Build the shared team query with normalized actor authorization."""

    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        parsed = team_query_input(text)
        if parsed is not None and not context.has_member_mentions:
            return await query_portable_team_ids(
                service,
                features,
                context,
                service.parse_team_ids(parsed.argument),
            )
        reference = team_player_query_reference(text)
        if reference is None:
            msg = f"catalog accepted input that its team parser rejected: {text!r}"
            raise ValueError(msg)
        if not features.is_feature_allowed(
            context.message.actor, context.message.conversation, "seer_team"
        ):
            return OutboundMessage.from_text("该功能当前未对你开放。")
        resolved = resolver.resolve(context, reference, allow_default_binding=False)
        if resolved.error is not None:
            return OutboundMessage.from_text(resolved.error)
        if resolved.player_id is None:
            msg = "resolved team query has no player ID"
            raise ValueError(msg)
        result = await service.query_player_team(
            resolved.player_id,
            team_query_actor(features, context),
        )
        return OutboundMessage.from_text(result)

    return execute


async def query_portable_team_ids(
    service: SeerTeamQueryService,
    features: FeatureService,
    context: MessageInputContext,
    team_ids: tuple[int, ...],
) -> OutboundMessage:
    """Execute direct commands and menu selections through the same team policy."""
    message = context.message
    if not features.is_feature_allowed(
        message.actor, message.conversation, "seer_team"
    ):
        return OutboundMessage.from_text("该功能当前未对你开放。")
    result = await service.query(
        team_ids,
        team_query_actor(features, context),
    )
    return OutboundMessage.from_text(result)


def team_query_actor(
    features: FeatureService, context: MessageInputContext
) -> TeamQueryActor:
    message = context.message
    return TeamQueryActor(
        actor=message.actor,
        conversation=message.conversation
        if message.conversation.kind == "group"
        else None,
        can_manage=can_manage_group_actor(features, message.actor, message.group_role),
    )


def build_portable_rank_help_operation(
    catalog: CommandCatalog,
    features: FeatureService,
) -> PortableOperation:
    """Build role-aware rank help from the shared command catalog."""

    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        command_help = catalog.format_for_context(
            command_context_from_input(context),
            features,
            plugin_id="rank_help",
        )
        return OutboundMessage.from_text(
            f"📊【可用榜单】\n{format_rank_help(command_help)}"
        )

    return execute


def _affix_argument(parser: AffixParser):
    def parse(text: str) -> str | None:
        parsed = parser(text)
        return None if parsed is None else parsed.argument

    return parse


def _equipment_queries() -> tuple[tuple[EquipmentKind, AffixParser, str, str], ...]:
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


def build_portable_peak_query_operation(
    service: PeakQueryService,
) -> PortableOperation:
    """Build pool and vote queries with delivery-gated rendering progress."""

    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        del context

        async def query(progress: ProgressReporter) -> OutboundMessage:
            try:
                if text in PEAK_POOL_COMMANDS:
                    result = await service.pool(expert=False, progress=progress)
                elif text in PEAK_EXPERT_POOL_COMMANDS:
                    result = await service.pool(expert=True, progress=progress)
                elif text in PEAK_MASTER_POOL_COMMANDS:
                    result = await service.master_pool(progress)
                elif text in PEAK_VOTE_COMMANDS:
                    result = await service.vote(progress)
                else:
                    msg = f"unsupported portable peak query command: {text!r}"
                    raise ValueError(msg)
            except DataUnavailableError:
                return OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
            return result.to_outbound()

        return await progress_operation_reply(query)

    return execute


def build_portable_peak_rank_operation(
    service: PeakQueryService,
) -> PortableOperation:
    """Build item and pet ranks with delivery-gated rendering progress."""

    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        del context

        async def query(progress: ProgressReporter) -> OutboundMessage:
            try:
                if text in PEAK_SUIT_RANK_COMMANDS:
                    result = await service.item_rank(text, kind="套装")
                elif text in PEAK_TITLE_RANK_COMMANDS:
                    result = await service.item_rank(text, kind="称号")
                elif text in PEAK_PET_RANK_COMMANDS:
                    result = await service.pet_rank(text, progress)
                else:
                    msg = f"unsupported portable peak rank command: {text!r}"
                    raise ValueError(msg)
            except DataUnavailableError:
                return OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
            return result.to_outbound()

        return await progress_operation_reply(query)

    return execute
