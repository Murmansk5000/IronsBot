# SPDX-License-Identifier: MIT
"""Platform-neutral execution for commands selected by the shared catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ironsbot.core.command_catalog import CommandContext
from ironsbot.core.commands import command_text_matches, normalize_command_text
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.data_query_commands import (
    DATA_VERSION_COMMANDS,
    SEASON_COUNTDOWN_COMMANDS,
    WEEKLY_PREVIEW_COMMANDS,
)
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping

    from ironsbot.core.command_catalog import CommandCatalog, CommandContract
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.platform import ActorRef, ConversationRef
    from ironsbot.services.about import AboutService
    from ironsbot.services.seer.data_queries import DataQueryReply


class PortableOperation(Protocol):
    def __call__(
        self, text: str
    ) -> Awaitable[OutboundMessage | str | DataQueryImageReply]: ...


class PortableDataQueries(Protocol):
    async def data_version(self) -> DataQueryReply: ...

    async def season_countdown(self) -> DataQueryReply: ...

    async def weekly_preview(self) -> DataQueryReply: ...


class PortableCommandRouter:
    """Dispatch catalog-owned commands without importing a platform adapter."""

    def __init__(
        self,
        catalog: CommandCatalog,
        operations: Mapping[str, PortableOperation],
        features: FeatureService,
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

    def recognizes(
        self,
        text: str,
        *,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> bool:
        command = _command_text(text)
        context = CommandContext(actor=actor, conversation=conversation)
        return self._matching_contract(command, context=context) is not None

    async def dispatch(
        self,
        text: str,
        *,
        actor: ActorRef,
        conversation: ConversationRef,
    ) -> OutboundMessage | None:
        command = _command_text(text)
        context = CommandContext(actor=actor, conversation=conversation)
        contract = self._matching_contract(command, context=context)
        if contract is None:
            return None
        if contract.id == "help":
            return self._help(context)
        try:
            result = await self._operations[contract.id](command)
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
    data_queries: PortableDataQueries,
    features: FeatureService,
) -> PortableCommandRouter:
    async def about_message(text: str) -> OutboundMessage:
        del text
        return about.message()

    async def data_query(text: str) -> DataQueryReply:
        if command_text_matches(text, DATA_VERSION_COMMANDS):
            return await data_queries.data_version()
        if command_text_matches(text, SEASON_COUNTDOWN_COMMANDS):
            return await data_queries.season_countdown()
        if command_text_matches(text, WEEKLY_PREVIEW_COMMANDS):
            return await data_queries.weekly_preview()
        msg = f"unsupported portable Seer data command: {text!r}"
        raise ValueError(msg)

    return PortableCommandRouter(
        catalog,
        {"about": about_message, "seer.data.query": data_query},
        features,
    )


def _command_text(text: str) -> str:
    normalized = normalize_command_text(text)
    return (
        normalize_command_text(normalized[1:])
        if normalized.startswith("/")
        else normalized
    )
