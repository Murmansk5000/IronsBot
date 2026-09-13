# SPDX-License-Identifier: MIT
"""Platform-neutral execution for commands selected by the shared catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.command_catalog import CommandContext
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
from ironsbot.services.portable_operational_commands import (
    build_portable_data_sync_operations,
    build_portable_docker_operations,
    build_portable_meeting_operations,
    build_portable_server_status_operations,
)
from ironsbot.services.portable_pet_config_commands import (
    build_portable_pet_config_operation,
)
from ironsbot.services.portable_player_commands import (
    build_portable_player_operations,
)
from ironsbot.services.portable_query_sessions import (
    PortableQuerySessions,
)
from ironsbot.services.portable_rank_commands import (
    build_portable_rank_admin_operations,
    build_portable_rank_operations,
)
from ironsbot.services.portable_reply import PortableOperation, PortableReply
from ironsbot.services.portable_seer_commands import build_portable_seer_operations
from ironsbot.services.portable_team_resource_commands import (
    build_portable_team_resource_operations,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from ironsbot.core.command_catalog import CommandCatalog, CommandContract
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.about import AboutService
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.bilibili.runtime import BilibiliMonitorService
    from ironsbot.services.bilibili.service import BilibiliService
    from ironsbot.services.messaging.push_time import PushTimeOption
    from ironsbot.services.messaging.sendpic import SendpicService
    from ironsbot.services.messaging.service import MessagingService
    from ironsbot.services.operations.data_sync import DataSyncService
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.server_status import ServerStatusService
    from ironsbot.services.pet_config import PetConfigQueryService
    from ironsbot.services.seer.new_content import NewContentCategory
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
        return self._query_sessions.recognizes_response(command, context) or (
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
            selected = await self._query_sessions.select(
                command,
                context,
                allow_deferred=True,
            )
        except DataUnavailableError:
            return PortableReply(
                OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
            )
        if selected is not None:
            return (
                selected
                if isinstance(selected, PortableReply)
                else PortableReply(selected)
            )
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
    refresh_push_time_jobs: Callable[[PushTimeOption], Awaitable[None]] | None = None,
    sendpic: SendpicService | None = None,
    bilibili: BilibiliService | None = None,
    bilibili_monitor: BilibiliMonitorService | None = None,
    server_status: ServerStatusService | None = None,
    data_sync: DataSyncService | None = None,
    docker_update: DockerUpdateService | None = None,
    meeting_number: str = "",
    meeting_template: str = "{meeting_number}",
    pet_config: PetConfigQueryService | None = None,
    image_command_texts: frozenset[str] = frozenset(),
    new_content_expanded_categories: frozenset[NewContentCategory] = frozenset(),
    new_content_preview_max_items: int = 5,
) -> PortableCommandRouter:
    async def about_message(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text, context
        return about.message()

    sessions = PortableQuerySessions()
    seer_operations = build_portable_seer_operations(
        catalog,
        seer,
        sessions,
        features,
    )
    player_operations = build_portable_player_operations(
        seer.player,
        player_id_resolver,
        sessions,
    )
    rank_operations = _catalog_operations(
        catalog,
        build_portable_rank_operations(
            seer.rank_queries,
            player_id_resolver,
        ),
    )
    rank_admin_operations = _catalog_operation_family(
        catalog,
        {
            "rank.sample_status",
            "rank.sample_refresh",
            "rank.page_status",
            "rank.page_refresh",
            "rank.page_batch",
        },
        lambda: build_portable_rank_admin_operations(seer.rank_admin),
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
            else build_portable_messaging_operations(
                messaging,
                sessions,
                refresh_push_time_jobs=refresh_push_time_jobs,
            )
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
                refresh_now=bilibili_monitor.manual_refresh,
            )
        ),
    )
    server_status_operations = _catalog_operations(
        catalog,
        (
            {}
            if server_status is None
            else build_portable_server_status_operations(server_status)
        ),
    )
    data_sync_operations = _catalog_operations(
        catalog,
        (
            {}
            if data_sync is None
            else build_portable_data_sync_operations(data_sync, sessions)
        ),
    )
    docker_operations = _catalog_operations(
        catalog,
        (
            {}
            if docker_update is None
            else build_portable_docker_operations(docker_update)
        ),
    )
    meeting_operations = _catalog_operations(
        catalog,
        build_portable_meeting_operations(meeting_number, meeting_template),
    )
    pet_config_operations = (
        {}
        if pet_config is None or "pet_config.query" not in catalog.command_ids
        else {
            "pet_config.query": build_portable_pet_config_operation(
                pet_config,
                sessions,
                image_command_texts=image_command_texts,
            )
        }
    )

    operations: dict[str, PortableOperation] = {
        "about": about_message,
        **seer_operations,
        **team_resource_operations,
        **activity_operations,
        **messaging_operations,
        **sendpic_operations,
        **bilibili_operations,
        **server_status_operations,
        **data_sync_operations,
        **docker_operations,
        **meeting_operations,
        **pet_config_operations,
        **new_content_operations,
        **autocard_operations,
        **countermark_operations,
        **player_operations,
        **rank_operations,
        **rank_admin_operations,
    }
    return PortableCommandRouter(
        catalog,
        operations,
        features,
        ai=ai,
        query_sessions=sessions,
    )


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


def _command_context(context: MessageInputContext) -> CommandContext:
    message = context.message
    return CommandContext(
        actor=message.actor,
        conversation=message.conversation,
        group_role=message.group_role,
        member_mentions=message.direct_mentions,
    )


def _command_text(text: str) -> str:
    stripped = text.strip()
    return stripped[1:].strip() if stripped.startswith("/") else stripped
