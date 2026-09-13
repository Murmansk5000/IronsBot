# SPDX-License-Identifier: MIT
"""Platform-neutral execution for commands selected by the shared catalog."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Protocol

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.commands import command_text_matches, normalize_command_text
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.portable_query_sessions import (
    PortableQuerySessions,
    QueryOperationSpec,
    build_query_operation,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
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
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping

    from ironsbot.core.affix_commands import AffixParser
    from ironsbot.core.command_catalog import CommandCatalog, CommandContract
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.about import AboutService
    from ironsbot.services.seer.data_queries import DataQueryReply
    from ironsbot.services.seer.equipment import EquipmentKind
    from ironsbot.services.seer.resources import SeerQueryResources


class PortableOperation(Protocol):
    def __call__(
        self, text: str, context: CommandContext
    ) -> Awaitable[OutboundMessage | str | DataQueryImageReply]: ...


class PortableCommandRouter:
    """Dispatch catalog-owned commands without importing a platform adapter."""

    def __init__(
        self,
        catalog: CommandCatalog,
        operations: Mapping[str, PortableOperation],
        features: FeatureService,
        *,
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
        self._query_sessions = query_sessions or PortableQuerySessions()

    def recognizes(
        self,
        text: str,
        *,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> bool:
        command = _command_text(text)
        context = CommandContext(actor=actor, conversation=conversation)
        return self._query_sessions.recognizes_selection(command, context) or (
            self._matching_contract(command, context=context) is not None
        )

    async def dispatch(  # noqa: PLR0911 - normalize every supported result shape
        self,
        text: str,
        *,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> OutboundMessage | None:
        command = _command_text(text)
        context = CommandContext(actor=actor, conversation=conversation)
        try:
            selected = await self._query_sessions.select(command, context)
        except DataUnavailableError:
            return OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
        if selected is not None:
            return selected
        contract = self._matching_contract(command, context=context)
        if contract is None:
            return None
        if contract.id == "help":
            return self._help(context)
        try:
            result = await self._operations[contract.id](command, context)
        except DataUnavailableError:
            return OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
        if isinstance(result, OutboundMessage):
            return result
        if isinstance(result, DataQueryImageReply):
            return result.to_outbound()
        return OutboundMessage.from_text(result)

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

    def _available_contracts(
        self, context: CommandContext
    ) -> tuple[CommandContract, ...]:
        executable_ids = self._operations.keys() | {"help"}
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


def build_portable_command_router(
    *,
    catalog: CommandCatalog,
    about: AboutService,
    seer: SeerQueryResources,
    features: FeatureService,
) -> PortableCommandRouter:
    async def about_message(text: str, context: CommandContext) -> OutboundMessage:
        del text, context
        return about.message()

    async def data_query(text: str, context: CommandContext) -> DataQueryReply:
        del context
        if command_text_matches(text, DATA_VERSION_COMMANDS):
            return await seer.data_queries.data_version()
        if command_text_matches(text, SEASON_COUNTDOWN_COMMANDS):
            return await seer.data_queries.season_countdown()
        if command_text_matches(text, WEEKLY_PREVIEW_COMMANDS):
            return await seer.data_queries.weekly_preview()
        msg = f"unsupported portable Seer data command: {text!r}"
        raise ValueError(msg)

    sessions = PortableQuerySessions()
    operations: dict[str, PortableOperation] = {
        "about": about_message,
        "seer.data.query": data_query,
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
        query_sessions=sessions,
    )


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
    async def execute(text: str, context: CommandContext):
        operation = next(
            (operation for parser, operation in routes if parser(text) is not None),
            None,
        )
        if operation is None:
            msg = f"catalog accepted input that no portable operation owns: {text!r}"
            raise ValueError(msg)
        return await operation(text, context)

    return execute


def _command_text(text: str) -> str:
    normalized = normalize_command_text(text)
    return (
        normalize_command_text(normalized[1:])
        if normalized.startswith("/")
        else normalized
    )
