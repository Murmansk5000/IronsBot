# SPDX-License-Identifier: MIT
"""Platform-neutral player commands keyed by opaque actor identity."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.selection import format_selection_menu
from ironsbot.core.semantic_requests import SemanticRequest, SemanticRequestSource
from ironsbot.services.player_binding_confirmation import confirm_shortcut_binding
from ironsbot.services.player_extension_commands import query_player_extension
from ironsbot.services.player_reference_selection import (
    select_player_reference,
    select_player_target,
)
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.portable_reply import PortableReply, progress_operation_reply
from ironsbot.services.seer.player_detail_extensions import (
    PlayerDetailExtensionAction,
)
from ironsbot.services.seer.player_query import (
    available_player_detail_requests,
    extract_player_binding_arg,
    extract_player_query_arg,
)
from ironsbot.services.seer.player_shortcut_contracts import (
    PlayerShortcutCommand,
    execute_player_shortcut,
    parse_player_shortcut_command,
    player_shortcut_semantic_request,
)
from ironsbot.services.seer.rank_list_models import GLOBAL_RANKS, RankPlayerCommand

if TYPE_CHECKING:
    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ActorRef
    from ironsbot.services.portable_query_sessions import (
        MenuSelect,
        PortableQuerySessions,
    )
    from ironsbot.services.portable_reply import PortableOperation, ProgressReporter
    from ironsbot.services.seer.player_detail_extensions import (
        PlayerDetailExtensionRegistry,
    )
    from ironsbot.services.seer.player_id_resolver import (
        PlayerIdResolver,
        PlayerTargetSource,
    )
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.player_service_models import PlayerQueryResult
    from ironsbot.services.seer.rank_queries import RankQueryService


def build_portable_player_operations(  # noqa: PLR0913 - composed query dependencies
    service: PlayerService,
    resolver: PlayerIdResolver,
    sessions: PortableQuerySessions,
    features: FeatureService,
    extensions: PlayerDetailExtensionRegistry,
    rank_queries: RankQueryService | None = None,
) -> dict[str, PortableOperation]:
    owner = _PortablePlayerOperations(
        service, resolver, sessions, features, extensions, rank_queries
    )
    return {
        "seer.player.query": owner.query,
        "seer.player.default": owner.shortcut,
        "seer.player.bind": owner.bind,
        "seer.player.unbind": owner.unbind,
    }


@dataclass(frozen=True, slots=True)
class _PortablePlayerOperations:
    service: PlayerService
    resolver: PlayerIdResolver
    sessions: PortableQuerySessions
    features: FeatureService
    extensions: PlayerDetailExtensionRegistry
    rank_queries: RankQueryService | None

    async def query(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        reference = extract_player_query_arg(text)
        if reference is None:
            msg = f"catalog accepted input that its player parser rejected: {text!r}"
            raise ValueError(msg)
        target_source: PlayerTargetSource = (
            "member"
            if context.has_member_mentions
            else self.resolver.reference_source(reference)
            if reference.strip()
            else "default"
        )

        async def query(player_id: int, context: MessageInputContext) -> PortableReply:
            reservation = self.sessions.reserve_responses(
                context,
                lambda value: value.strip().isdigit(),
            )
            try:
                result = await self.service.query(
                    player_id,
                    actor=context.message.actor,
                    explicit=bool(reference.strip()),
                    conversation=context.message.conversation,
                )
                if not context.offer_player_binding or context.has_member_mentions:
                    result = replace(result, offer_binding=False)
                reply = _prepare_player_query_reply(
                    self.service,
                    self.resolver,
                    self.sessions,
                    context,
                    result,
                    self.features,
                    self.extensions,
                    self.rank_queries,
                    target_source=target_source,
                )
            except BaseException:
                reservation.cancel()
                raise
            if not self.sessions.has_active_session(context):
                reservation.cancel()
                return reply
            return reservation.guard(reply)

        return await select_player_target(
            reference,
            context,
            self.resolver,
            self.sessions,
            query,
            title="请选择要查询的玩家：",
        )

    async def bind(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        reference = extract_player_binding_arg(text)
        if reference is None:
            msg = f"catalog accepted input that its binding parser rejected: {text!r}"
            raise ValueError(msg)
        target = None
        if context.has_member_mentions:
            if context.message.conversation.kind != "group":
                return _text_reply("仅群聊可为成员绑定米米号。")
            if not self.features.is_actor_superuser(context.message.actor):
                return _text_reply("仅超级管理员可为其他成员绑定米米号。")
            if len(context.member_mentions) != 1:
                return _text_reply("请一次只 @ 一名成员绑定米米号。")
            target = context.member_mentions[0]

        async def execute(
            player_id: int, context: MessageInputContext
        ) -> PortableReply:
            return await self._bind_player(player_id, context, target)

        reply = await select_player_reference(
            reference,
            context,
            self.resolver,
            self.sessions,
            execute,
            title="请选择要绑定的玩家：",
        )
        return reply if isinstance(reply, PortableReply) else PortableReply(reply)

    async def _bind_player(
        self,
        player_id: int,
        context: MessageInputContext,
        target: ActorRef | None,
    ) -> PortableReply:
        if target is not None and not self.features.is_actor_superuser(
            context.message.actor
        ):
            return _text_reply("仅超级管理员可为其他成员绑定米米号。")
        result = await self.service.bind_player(
            player_id,
            actor=context.message.actor,
            conversation=context.message.conversation,
            target=target,
        )
        if result.pending is not None and result.binding_replacement is not None:
            return _offer_binding_confirmation(
                self.service,
                self.resolver,
                self.sessions,
                context,
                result,
                self.features,
                self.extensions,
                self.rank_queries,
            )
        return _prepare_player_query_reply(
            self.service,
            self.resolver,
            self.sessions,
            context,
            result,
            self.features,
            self.extensions,
            self.rank_queries,
        )

    async def unbind(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        return OutboundMessage.from_text(self.service.unbind(context.message.actor))

    async def shortcut(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply:
        parsed = parse_player_shortcut_command(text)
        if parsed is None:
            msg = f"catalog accepted input that its shortcut parser rejected: {text!r}"
            raise ValueError(msg)

        async def query(player_id: int, context: MessageInputContext) -> PortableReply:
            if parsed.kind == "beast_rank":
                if self.rank_queries is None or not self.features.is_feature_allowed(
                    context.message.actor, context.message.conversation, "seer_rank"
                ):
                    return _text_reply("该功能当前未对你开放。")
                return await _beast_rank_reply(self.rank_queries, player_id, context)
            return await _player_shortcut_reply(
                self.service,
                PlayerShortcutCommand(parsed.kind, player_id),
                context,
            )

        async def confirmed_query(
            player_id: int, query_context: MessageInputContext
        ) -> PortableReply:
            if not parsed.player_reference:
                return await query(player_id, query_context)
            return await confirm_shortcut_binding(
                self.service, self.sessions, player_id, query_context, query
            )

        return await select_player_target(
            parsed.player_reference,
            context,
            self.resolver,
            self.sessions,
            confirmed_query,
            title="请选择要查询的玩家：",
        )


async def _player_shortcut_reply(
    service: PlayerService,
    command: PlayerShortcutCommand,
    context: MessageInputContext,
) -> PortableReply:
    async def execute(send_status: ProgressReporter) -> OutboundMessage:
        reply = await execute_player_shortcut(
            service,
            command,
            context.message.actor,
            conversation=context.message.conversation,
            send_status=send_status,
        )
        return reply.to_outbound()

    return await progress_operation_reply(execute)


async def _beast_rank_reply(
    rank_queries: RankQueryService,
    player_id: int,
    context: MessageInputContext,
) -> PortableReply:
    replies = []
    for key, spec in GLOBAL_RANKS.items():
        if not spec.beast_metric:
            continue
        replies.append(
            await rank_queries.prepare_player(
                RankPlayerCommand(key, player_id),
                actor=context.message.actor,
                conversation=context.message.conversation,
            )
        )

    def delivered() -> None:
        for reply in replies:
            reply.delivered()

    return PortableReply(
        OutboundMessage.from_text(
            "【神兽榜】\n\n" + "\n\n".join(reply.message for reply in replies)
        ),
        on_delivered=delivered,
    )


def _offer_binding_confirmation(  # noqa: PLR0913 - preserves query context
    service: PlayerService,
    resolver: PlayerIdResolver,
    sessions: PortableQuerySessions,
    context: MessageInputContext,
    result: PlayerQueryResult,
    features: FeatureService,
    extensions: PlayerDetailExtensionRegistry,
    rank_queries: RankQueryService | None,
) -> PortableReply:
    pending = result.pending
    if pending is None:
        msg = "binding confirmation requires a pending player query"
        raise ValueError(msg)

    async def confirm(
        choice: Literal["confirm", "keep"],
        selection_context: MessageInputContext,
    ) -> PortableReply:
        service.save_binding_choice(
            selection_context.message.actor,
            pending,
            accepted=choice == "confirm",
            replacing_existing=result.binding_replacement is not None,
        )
        return _prepare_player_query_reply(
            service,
            resolver,
            sessions,
            selection_context,
            replace(result, offer_binding=False, binding_replacement=None),
            features,
            extensions,
            rank_queries,
        )

    return PortableReply(
        sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=("confirm", "keep"),
                choice_keys=("confirm", "keep"),
                select=confirm,
                prompt=OutboundMessage.from_text(
                    service.binding_offer(
                        pending,
                        replacement=result.binding_replacement,
                    )
                ),
                labels=("确认绑定", "保留原绑定"),
                text_inputs=(
                    frozenset({"是", "y", "yes", "确认", "确定"}),
                    frozenset({"否", "n", "no", "取消"}),
                ),
                invalid_choice_message="请回复“是”或“否”，或输入 0 退出。",
                exit_message=(
                    "已保留原绑定。"
                    if result.binding_replacement is not None
                    else "已退出绑定选择。"
                ),
            ),
        )
    )


def _prepare_player_query_reply(  # noqa: C901, PLR0913 - dynamic menu choices
    service: PlayerService,
    resolver: PlayerIdResolver,
    sessions: PortableQuerySessions,
    context: MessageInputContext,
    result: PlayerQueryResult,
    features: FeatureService,
    extensions: PlayerDetailExtensionRegistry,
    rank_queries: RankQueryService | None,
    *,
    target_source: PlayerTargetSource = "numeric",
) -> PortableReply:
    if result.message:
        return _text_reply(result.message)
    pending = result.pending
    if pending is None:
        msg = "player query returned neither a message nor pending data"
        raise ValueError(msg)

    player_message = pending.player_message
    if result.offer_binding:
        return _offer_binding_confirmation(
            service,
            resolver,
            sessions,
            context,
            result,
            features,
            extensions,
            rank_queries,
        )
    requests = available_player_detail_requests(
        has_collection=pending.section_plan.has_collection,
        has_peak=pending.section_plan.needs_peak_section,
        has_autocard=pending.section_plan.has_autocard_rank,
    )
    show_beast_rank = rank_queries is not None and features.is_feature_allowed(
        context.message.actor,
        context.message.conversation,
        "seer_rank",
    )
    team_id = int(getattr(pending.user_info, "team_id", 0) or 0)
    extension_actions = tuple(
        action
        for action in extensions.actions()
        if action.id != "player_team" or team_id > 0
        if features.is_feature_allowed(
            context.message.actor,
            context.message.conversation,
            action.feature,
        )
    )

    async def select(
        command: (
            PlayerShortcutCommand
            | PlayerDetailExtensionAction
            | Literal["beast_rank", "bind", "decline"]
        ),
        context: MessageInputContext,
    ) -> OutboundMessage | PortableReply:
        error = resolver.query_access_error(
            context.message.actor, pending.player_id, target_source
        )
        if error is not None:
            return OutboundMessage.from_text(error)
        if command == "beast_rank":
            rank_service = rank_queries
            assert rank_service is not None
            if not context.is_reply and context.text.strip() == "神兽榜":
                return await select_player_target(
                    "",
                    context,
                    resolver,
                    sessions,
                    lambda player_id, query_context: _beast_rank_reply(
                        rank_service, player_id, query_context
                    ),
                    title="请选择要查询的玩家：",
                )
            return await _beast_rank_reply(rank_service, pending.player_id, context)
        if isinstance(command, str):
            msg = "unknown player detail action"
            raise TypeError(msg)
        if isinstance(command, PlayerDetailExtensionAction):
            return await query_player_extension(
                command,
                pending.player_id,
                context,
                features,
            )
        return await _player_shortcut_reply(service, command, context)

    async def shared_select(
        command: (
            PlayerShortcutCommand
            | PlayerDetailExtensionAction
            | Literal["beast_rank", "bind", "decline"]
        ),
        context: MessageInputContext,
    ) -> OutboundMessage | PortableReply:
        error = resolver.query_access_error(
            context.message.actor, pending.player_id, "shared_menu"
        )
        if error is not None:
            return OutboundMessage.from_text(error)
        return await _select_shared_player_detail(
            command,
            context,
            sessions=sessions,
            features=features,
            select=select,
        )

    def semantic_request(
        command: (
            PlayerShortcutCommand
            | PlayerDetailExtensionAction
            | Literal["beast_rank", "bind", "decline"]
        ),
        _context: MessageInputContext,
    ) -> SemanticRequest | None:
        return _player_detail_semantic_request(command, pending.player_id)

    choices: tuple[
        PlayerShortcutCommand
        | PlayerDetailExtensionAction
        | Literal["beast_rank", "bind", "decline"],
        ...,
    ] = (
        *(
            PlayerShortcutCommand(
                request.kind, pending.player_id, pending.base_snapshot
            )
            for request in requests
        ),
        *(("beast_rank",) if show_beast_rank else ()),
        *extension_actions,
    )
    labels = (
        *(f"【{request.menu_label}】" for request in requests),
        *(("【神兽榜】",) if show_beast_rank else ()),
        *(
            f"【{action.label}】"
            f"{(pending.base_snapshot.team_name.strip() or '未知战队')}"
            f"（战队ID：{team_id}）"
            if action.id == "player_team" and pending.base_snapshot is not None
            else f"【{action.label}】"
            for action in extension_actions
        ),
    )
    menu = sessions.offer_menu(
        context,
        PortableMenuSpec(
            choices=choices,
            select=select,
            labels=labels,
            text_inputs=(
                *(frozenset({request.menu_label}) for request in requests),
                *((frozenset({"神兽榜"}),) if show_beast_rank else ()),
                *(frozenset(action.aliases) for action in extension_actions),
            ),
            shared_select=shared_select,
            access=lambda responder: features.is_feature_allowed(
                responder.message.actor, responder.message.conversation, "seer_player"
            ),
            can_select=lambda command, responder: features.is_feature_allowed(
                responder.message.actor,
                responder.message.conversation,
                command.feature
                if isinstance(command, PlayerDetailExtensionAction)
                else "seer_rank"
                if command == "beast_rank"
                else "seer_player",
            ),
            semantic_request=semantic_request,
            shared_choice_indexes=frozenset(
                range(
                    1,
                    len(requests) + int(show_beast_rank) + len(extension_actions) + 1,
                )
            ),
            keep_open=True,
            exit_message="已退出米米号详情查询。",
            prompt=OutboundMessage.from_text(
                format_selection_menu(
                    title=f"{player_message}\n回复数字或栏目名称查看详情：",
                    items=labels,
                )
                if choices
                else player_message
            ),
        ),
    )

    def delivered() -> None:
        service.record_returned_query(context.message.actor, pending)
        service.start_background_refresh(
            pending,
            conversation=context.message.conversation,
        )

    return PortableReply(menu, on_delivered=delivered)


async def _select_shared_player_detail(
    command: (
        PlayerShortcutCommand
        | PlayerDetailExtensionAction
        | Literal["beast_rank", "bind", "decline"]
    ),
    context: MessageInputContext,
    *,
    sessions: PortableQuerySessions,
    features: FeatureService,
    select: MenuSelect[
        PlayerShortcutCommand
        | PlayerDetailExtensionAction
        | Literal["beast_rank", "bind", "decline"]
    ],
) -> OutboundMessage | PortableReply:
    if isinstance(command, str) and command != "beast_rank":
        sessions.discard(context)
        return OutboundMessage.from_text("该选项仅限菜单发起者使用。")
    required_feature = (
        command.feature
        if isinstance(command, PlayerDetailExtensionAction)
        else "seer_rank"
        if command == "beast_rank"
        else "seer_player"
    )
    if not features.is_feature_allowed(
        context.message.actor,
        context.message.conversation,
        required_feature,
    ):
        sessions.discard(context)
        return OutboundMessage.from_text("该功能当前未对你开放。")
    return await select(command, context)


def _player_detail_semantic_request(
    command: (
        PlayerShortcutCommand
        | PlayerDetailExtensionAction
        | Literal["beast_rank", "bind", "decline"]
    ),
    player_id: int,
) -> SemanticRequest | None:
    if isinstance(command, str):
        return None
    request = player_shortcut_semantic_request(
        kind=(
            command.kind if isinstance(command, PlayerShortcutCommand) else "collection"
        ),
        player_id=player_id,
        source=SemanticRequestSource.MENU,
    )
    if isinstance(command, PlayerDetailExtensionAction):
        return SemanticRequest(
            action=command.action,
            target=request.target,
            source=SemanticRequestSource.EXTENSION,
        )
    return request


def _text_reply(message: str) -> PortableReply:
    return PortableReply(OutboundMessage.from_text(message))
