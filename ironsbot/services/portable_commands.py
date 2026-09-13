# SPDX-License-Identifier: MIT
"""Platform-neutral execution for commands selected by the shared catalog."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.commands import command_text_matches
from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_activity_commands import (
    build_portable_activity_operations,
)
from ironsbot.services.portable_autocard_commands import (
    build_portable_autocard_operations,
)
from ironsbot.services.portable_bilibili_commands import (
    build_portable_bilibili_operations,
)
from ironsbot.services.portable_countermark_commands import (
    build_portable_countermark_operations,
)
from ironsbot.services.portable_messaging_commands import (
    build_portable_messaging_operations,
    build_portable_sendpic_operations,
)
from ironsbot.services.portable_new_content_commands import (
    build_portable_new_content_operations,
)
from ironsbot.services.portable_player_commands import (
    build_portable_player_operations,
)
from ironsbot.services.portable_query_sessions import (
    PortableQuerySessions,
    QueryOperationSpec,
    build_query_operation,
)
from ironsbot.services.portable_rank_commands import build_portable_rank_operations
from ironsbot.services.portable_reply import PortableOperation, PortableReply
from ironsbot.services.portable_team_resource_commands import (
    build_portable_team_resource_operations,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
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
    pet_image_input,
    pet_query_input,
    team_query_input,
)
from ironsbot.services.seer.rank_help import format_rank_help
from ironsbot.services.seer.team import TeamQueryActor

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ironsbot.core.affix_commands import AffixParser
    from ironsbot.core.command_catalog import CommandCatalog, CommandContract
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.about import AboutService
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.messaging.sendpic import SendpicService
    from ironsbot.services.messaging.service import MessagingService
    from ironsbot.services.seer.data_queries import DataQueryReply
    from ironsbot.services.seer.equipment import EquipmentKind
    from ironsbot.services.seer.new_content import NewContentCategory
    from ironsbot.services.seer.peak import PeakQueryService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.resources import SeerQueryResources
    from ironsbot.services.team.resource import TeamResourceService


class PortableCommandRouter:
    """Dispatch catalog-owned commands without importing a platform adapter."""

    def __init__(
        self,
        catalog: CommandCatalog,
        operations: Mapping[str, PortableOperation],
        features: FeatureService,
        *,
        ai: AiService,
        query_sessions: PortableQuerySessions | None = None,
    ) -> None:
        unknown = set(operations) - catalog.command_ids
        if unknown:
            msg = "portable operations reference unknown commands: " + ", ".join(
                sorted(unknown)
            )
            raise ValueError(msg)
        self._catalog = catalog
        self._operations = dict(operations)
        self._features = features
        self._ai = ai
        self._query_sessions = query_sessions or PortableQuerySessions()

    def recognizes(
        self,
        context: MessageInputContext,
    ) -> bool:
        if self._message_is_blocked(context):
            return False
        raw_command = context.text.strip()
        command = _command_text(context.text)
        command_context = _command_context(context)
        return self._query_sessions.recognizes_selection(command, context) or (
            self._matching_input_contract(
                raw_command,
                command,
                context=command_context,
            )
            is not None
        ) or self._can_chat(context, command_context) or self._is_group_mention(context)

    async def dispatch(  # noqa: PLR0911 - normalize every supported result shape
        self,
        context: MessageInputContext,
    ) -> PortableReply | None:
        if self._message_is_blocked(context):
            return None
        raw_command = context.text.strip()
        command = _command_text(context.text)
        command_context = _command_context(context)
        try:
            selected = await self._query_sessions.select(command, context)
        except DataUnavailableError:
            return PortableReply(
                OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
            )
        if selected is not None:
            return PortableReply(selected)
        contract = self._matching_input_contract(
            raw_command,
            command,
            context=command_context,
        )
        if contract is None:
            return await self._fallback_reply(context, command_context, command)
        if contract.id == "help":
            return PortableReply(self._help(command_context))
        try:
            result = await self._operations[contract.id](command, context)
        except DataUnavailableError:
            return PortableReply(
                OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
            )
        if isinstance(result, PortableReply):
            return result
        if isinstance(result, OutboundMessage):
            return PortableReply(result)
        if isinstance(result, DataQueryImageReply):
            return PortableReply(result.to_outbound())
        return PortableReply(OutboundMessage.from_text(result))

    def _matching_contract(
        self,
        text: str,
        *,
        context: CommandContext,
    ) -> CommandContract | None:
        return next(
            (
                contract
                for contract in self._available_contracts(context)
                if contract.matches_direct_input(context, text)
            ),
            None,
        )

    def _matching_input_contract(
        self,
        raw_text: str,
        normalized_text: str,
        *,
        context: CommandContext,
    ) -> CommandContract | None:
        contract = self._matching_contract(raw_text, context=context)
        if contract is not None or raw_text == normalized_text:
            return contract
        return self._matching_contract(normalized_text, context=context)

    def _available_contracts(
        self, context: CommandContext
    ) -> tuple[CommandContract, ...]:
        executable_ids = self._operations.keys() | {
            "help",
            "ai_chat.group",
            "ai_chat.private",
        }
        return tuple(
            contract
            for contract in self._catalog.available_for_context(
                context,
                self._features,
            )
            if contract.id in executable_ids
        )

    def _help(self, context: CommandContext) -> OutboundMessage:
        contracts = self._available_contracts(context)
        lines = ["【机器人调试功能】", "帮助 - 查看当前可用功能"]
        lines.extend(
            f"{contract.examples[0]} - {contract.description}"
            for contract in contracts
            if contract.id != "help"
        )
        return OutboundMessage.from_text("\n".join(lines))

    async def _fallback_reply(
        self,
        context: MessageInputContext,
        command_context: CommandContext,
        prompt: str,
    ) -> PortableReply | None:
        if self._can_chat(context, command_context):
            if not prompt:
                return PortableReply(
                    OutboundMessage.from_text("你想聊什么？可以直接写问题。")
                )
            message = context.message
            reply = await self._ai.chat_reply(
                actor=message.actor,
                conversation=message.conversation,
                prompt=prompt,
            )
            return (
                None
                if reply is None
                else PortableReply(OutboundMessage.from_text(reply))
            )
        if self._is_group_mention(context):
            return PortableReply(
                OutboundMessage.from_text(DIRECT_COMMAND_HELP_HINT_TEXT)
            )
        return None

    def _can_chat(
        self,
        context: MessageInputContext,
        command_context: CommandContext,
    ) -> bool:
        command_id = (
            "ai_chat.group"
            if context.message.conversation.kind == "group"
            else "ai_chat.private"
        )
        if command_id == "ai_chat.group" and not context.mentions_bot:
            return False
        return any(
            contract.id == command_id
            for contract in self._available_contracts(command_context)
        )

    def _message_is_blocked(self, context: MessageInputContext) -> bool:
        message = context.message
        return self._features.is_message_blocked(
            message.actor,
            message.conversation,
        )

    @staticmethod
    def _is_group_mention(context: MessageInputContext) -> bool:
        return (
            context.message.conversation.kind == "group" and context.mentions_bot
        )


def build_portable_command_router(  # noqa: PLR0913 - composition dependencies
    *,
    catalog: CommandCatalog,
    about: AboutService,
    seer: SeerQueryResources,
    player_id_resolver: PlayerIdResolver,
    features: FeatureService,
    ai: AiService,
    team_resource: TeamResourceService,
    activity: ActivityService | None = None,
    messaging: MessagingService | None = None,
    sendpic: SendpicService | None = None,
    bilibili: BilibiliService | None = None,
    bilibili_monitor: BilibiliMonitorService | None = None,
    new_content_expanded_categories: frozenset[NewContentCategory] = frozenset(),
    new_content_preview_max_items: int = 5,
) -> PortableCommandRouter:
    async def about_message(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text, context
        return about.message()

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

    async def team_query(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        parsed = team_query_input(text)
        if parsed is None:
            msg = f"catalog accepted input that its team parser rejected: {text!r}"
            raise ValueError(msg)
        message = context.message
        team_ids = seer.team_query.parse_team_ids(parsed.argument)
        result = await seer.team_query.query(
            team_ids,
            TeamQueryActor(
                actor=message.actor,
                conversation=message.conversation,
                can_manage=False,
            ),
        )
        return OutboundMessage.from_text(result)

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

    sessions = PortableQuerySessions()
    player_operations = build_portable_player_operations(
        seer.player,
        player_id_resolver,
        sessions,
    )
    rank_operations = build_portable_rank_operations(
        seer.rank_queries,
        player_id_resolver,
    )
    new_content_operations = _catalog_operations(
        catalog,
        build_portable_new_content_operations(
            seer,
            sessions,
            features,
            expanded_categories=new_content_expanded_categories,
            preview_max_items=new_content_preview_max_items,
        ),
    )
    autocard_operations = _catalog_operation_family(
        catalog,
        {"seer.autocard.query", "seer.autocard.sanctuary"},
        lambda: build_portable_autocard_operations(
            seer.autocard, seer.autocard_media, seer.autocard_sanctuary, sessions
        ),
    )
    countermark_operations = _catalog_operation_family(
        catalog,
        {"seer.mintmark.rank"},
        lambda: build_portable_countermark_operations(seer.countermark_rank),
    )
    team_resource_operations = _catalog_operations(
        catalog,
        build_portable_team_resource_operations(team_resource),
    )
    activity_operations = _catalog_operations(
        catalog,
        {} if activity is None else build_portable_activity_operations(activity),
    )
    messaging_operations = _catalog_operations(
        catalog,
        (
            {}
            if messaging is None
            else build_portable_messaging_operations(messaging, sessions)
        ),
    )
    sendpic_operations = _catalog_operations(
        catalog,
        {} if sendpic is None else build_portable_sendpic_operations(sendpic),
    )
    bilibili_operations = _catalog_operations(
        catalog,
        (
            {}
            if bilibili is None or bilibili_monitor is None
            else build_portable_bilibili_operations(
                bilibili,
                sessions,
                notify_auth_invalid=bilibili_monitor.notify_auth_invalid,
            )
        ),
    )

    operations: dict[str, PortableOperation] = {
        "about": about_message,
        "seer.data.query": data_query,
        "seer.team.query": team_query,
        **team_resource_operations,
        **activity_operations,
        **messaging_operations,
        **sendpic_operations,
        **bilibili_operations,
        **new_content_operations,
        **autocard_operations,
        **countermark_operations,
        **player_operations,
        "rank.help": rank_help_message,
        **rank_operations,
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
    return PortableCommandRouter(
        catalog,
        operations,
        features,
        ai=ai,
        query_sessions=sessions,
    )


def _affix_argument(parser: AffixParser):
    def parse(text: str) -> str | None:
        parsed = parser(text)
        return None if parsed is None else parsed.argument

    return parse


def _catalog_operations(
    catalog: CommandCatalog,
    operations: Mapping[str, PortableOperation],
) -> dict[str, PortableOperation]:
    return {
        command_id: operation
        for command_id, operation in operations.items()
        if command_id in catalog.command_ids
    }


def _catalog_operation_family(
    catalog: CommandCatalog,
    command_ids: set[str],
    factory: Callable[[], Mapping[str, PortableOperation]],
) -> dict[str, PortableOperation]:
    """Build one optional operation family only when its commands are loaded."""

    if catalog.command_ids.isdisjoint(command_ids):
        return {}
    return _catalog_operations(catalog, factory())


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


def _command_text(text: str) -> str:
    stripped = text.strip()
    return stripped[1:].strip() if stripped.startswith("/") else stripped
