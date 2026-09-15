# SPDX-License-Identifier: MIT
"""Portable Lucky Skin Window commands backed by explicit identity links."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import reference_digest
from ironsbot.core.selection import SelectionMenuItem, format_selection_menu
from ironsbot.services.player_reference_selection import select_player_reference
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.seer.lucky_skin_commands import (
    LUCKY_SKIN_WATCH_LIST_COMMANDS,
    LUCKY_SKIN_WATCH_REMOVE_COMMANDS,
    parse_lucky_skin_query,
    parse_lucky_skin_watch_target,
)
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinQuery,
    LuckySkinWatchItem,
    LuckySkinWindowAccessError,
    LuckySkinWindowBindingError,
    LuckySkinWindowError,
    LuckySkinWindowNotConfiguredError,
    LuckySkinWindowResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.platform import ActorRef
    from ironsbot.services.identity_linking import IdentityLinkingService
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation, PortableReply
    from ironsbot.services.seer.lucky_skin_window import LuckySkinWindowService
    from ironsbot.services.seer.pet_query import PetImageSelection, PetQueryService
    from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
    from ironsbot.services.seer.query_result import QueryChoice

logger = logging.getLogger(__name__)
_LINK_REQUIRED = (
    "❌ 当前官方身份尚未关联数字账号。\n"
    "请先在另一接入端私聊机器人发送“关联官方账号”获取令牌，"
    "再在这里发送“关联账号 <令牌>”。"
)
_Confirmation = Literal["confirm", "cancel"]


def build_portable_lucky_skin_operations(
    service: LuckySkinWindowService,
    pet: PetQueryService,
    identity_links: IdentityLinkingService,
    sessions: PortableQuerySessions,
    resolver: PlayerIdResolver,
) -> dict[str, PortableOperation]:
    commands = PortableLuckySkinCommands(
        service, pet, identity_links, sessions, resolver,
    )
    return {
        "seer.lucky_skin_window.query": commands.query,
        "seer.lucky_skin_window.watch.list": commands.watch_list,
        "seer.lucky_skin_window.watch.add": commands.watch_add,
        "seer.lucky_skin_window.watch.remove": commands.watch_remove,
        "seer.lucky_skin_window.watch.clear": commands.watch_clear,
        "seer.lucky_skin_window.watch.reset": commands.watch_reset,
    }


@dataclass(frozen=True, slots=True)
class PortableLuckySkinCommands:
    service: LuckySkinWindowService
    pet: PetQueryService
    identity_links: IdentityLinkingService
    sessions: PortableQuerySessions
    resolver: PlayerIdResolver

    async def query(
        self, text: str, context: MessageInputContext
    ) -> OutboundMessage | PortableReply:
        reference = parse_lucky_skin_query(text)
        if reference is None:
            msg = "invalid lucky window command"
            raise ValueError(msg)
        if reference and not context.has_member_mentions:
            async def execute(
                player_id: int, context: MessageInputContext,
            ) -> OutboundMessage:
                return await self._query_target(context, player_id)

            return await select_player_reference(
                reference, context, self.resolver, self.sessions, execute,
                title="请选择要查询橱窗的玩家：",
            )
        player_id = None
        if reference or context.has_member_mentions:
            resolution = self.resolver.resolve(context, reference)
            if resolution.error is not None:
                return OutboundMessage.from_text(resolution.error)
            player_id = resolution.player_id
        return await self._query_target(context, player_id)

    async def _query_target(
        self, context: MessageInputContext, player_id: int | None,
    ) -> OutboundMessage:
        actor = await self._linked_actor(context)
        if actor is None and player_id is None:
            return OutboundMessage.from_text(_LINK_REQUIRED)
        request = LuckySkinQuery(context.message.actor, actor, player_id)
        try:
            cached = self.service.cached_query(request)
        except LuckySkinWindowAccessError as error:
            return OutboundMessage.from_text(f"❌ {error}")
        except (
            LuckySkinWindowNotConfiguredError,
            LuckySkinWindowBindingError,
        ) as error:
            return OutboundMessage.from_text(_access_error(error, query=True))
        if cached is not None:
            return await self._result_menu(context, actor, cached)
        return self._confirmation_menu(context, request)

    async def watch_list(
        self, text: str, context: MessageInputContext
    ) -> OutboundMessage:
        del text
        return await self._watch_direct(context, self.service.watch_list_message)

    async def watch_add(
        self, text: str, context: MessageInputContext
    ) -> OutboundMessage:
        return await self._watch_change(
            context,
            text,
            commands=LUCKY_SKIN_WATCH_LIST_COMMANDS,
            watched=True,
        )

    async def watch_remove(
        self, text: str, context: MessageInputContext
    ) -> OutboundMessage:
        return await self._watch_change(
            context,
            text,
            commands=LUCKY_SKIN_WATCH_REMOVE_COMMANDS,
            watched=False,
        )

    async def watch_clear(
        self, text: str, context: MessageInputContext
    ) -> OutboundMessage:
        del text
        return await self._watch_direct(context, self.service.watch_clear_message)

    async def watch_reset(
        self, text: str, context: MessageInputContext
    ) -> OutboundMessage:
        del text
        return await self._watch_direct(context, self.service.watch_reset_message)

    async def _linked_actor(self, context: MessageInputContext) -> ActorRef | None:
        return await self.identity_links.linked_onebot_actor(context.message.actor)

    def _confirmation_menu(
        self,
        context: MessageInputContext,
        request: LuckySkinQuery,
    ) -> OutboundMessage:
        target_label = f"（米米号 {request.player_id}）" if request.player_id else ""
        async def select(
            choice: _Confirmation, context: MessageInputContext,
        ) -> OutboundMessage:
            if choice == "cancel":
                return OutboundMessage.from_text("已取消幸运橱窗查询。")
            return await self._query_now(context, request)

        return self.sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=("confirm", "cancel"),
                select=select,
                prompt=OutboundMessage.from_text(
                    f"今日幸运橱窗{target_label}尚未获取，需要登录查询。\n"
                    "1. 是，继续查询\n2. 否，取消查询\n0. 退出"
                ),
                labels=("确认查询", "取消查询"),
                exit_message="已取消幸运橱窗查询。",
            ),
        )

    async def _query_now(
        self,
        context: MessageInputContext,
        request: LuckySkinQuery,
    ) -> OutboundMessage:
        try:
            result = await self.service.query(request)
        except LuckySkinWindowAccessError as error:
            return OutboundMessage.from_text(f"❌ {error}")
        except (
            LuckySkinWindowNotConfiguredError,
            LuckySkinWindowBindingError,
        ) as error:
            return OutboundMessage.from_text(_access_error(error, query=True))
        except TimeoutError:
            return OutboundMessage.from_text("❌ 幸运橱窗查询超时，请稍后再试。")
        except LuckySkinWindowError as error:
            logger.warning(
                "lucky skin window query unavailable: platform=%s actor=%s error=%s",
                request.requester.platform.value,
                reference_digest(request.requester.id),
                error,
            )
            return OutboundMessage.from_text(
                "❌ 幸运橱窗数据暂时不可用，请稍后再试。"
            )
        except Exception:
            logger.exception(
                "lucky skin window query failed: platform=%s actor=%s",
                request.requester.platform.value,
                reference_digest(request.requester.id),
            )
            return OutboundMessage.from_text("❌ 幸运橱窗查询失败，请稍后再试。")
        return await self._result_menu(context, request.owner, result)

    async def _watch_direct(
        self,
        context: MessageInputContext,
        operation: Callable[[ActorRef], str],
    ) -> OutboundMessage:
        actor = await self._linked_actor(context)
        if actor is None:
            return OutboundMessage.from_text(_LINK_REQUIRED)
        try:
            return OutboundMessage.from_text(operation(actor))
        except (
            LuckySkinWindowNotConfiguredError,
            LuckySkinWindowBindingError,
        ) as error:
            return OutboundMessage.from_text(_access_error(error, query=False))

    async def _watch_change(
        self,
        context: MessageInputContext,
        text: str,
        *,
        commands: tuple[str, ...],
        watched: bool,
    ) -> OutboundMessage:
        actor = await self._linked_actor(context)
        if actor is None:
            return OutboundMessage.from_text(_LINK_REQUIRED)
        argument = parse_lucky_skin_watch_target(text, commands=commands) or ""
        try:
            candidates = self.service.resolve_watch_candidates(actor, argument)
        except (
            LuckySkinWindowNotConfiguredError,
            LuckySkinWindowBindingError,
        ) as error:
            return OutboundMessage.from_text(_access_error(error, query=False))
        if not candidates:
            return OutboundMessage.from_text(f"❌ 未找到皮肤：{argument}")
        if len(candidates) == 1:
            return OutboundMessage.from_text(
                self.service.watch_change_message(
                    actor,
                    candidates[0],
                    watched=watched,
                )
            )
        return self._watch_selection_menu(context, actor, candidates, watched=watched)

    def _watch_selection_menu(
        self,
        context: MessageInputContext,
        actor: ActorRef,
        candidates: tuple[LuckySkinWatchItem, ...],
        *,
        watched: bool,
    ) -> OutboundMessage:
        async def select(
            item: LuckySkinWatchItem, _context: MessageInputContext,
        ) -> OutboundMessage:
            return OutboundMessage.from_text(
                self.service.watch_change_message(actor, item, watched=watched)
            )

        prompt = format_selection_menu(
            title="请问你想管理的皮肤是……",
            items=tuple(
                SelectionMenuItem(item.name, detail_lines=(item.identifiers,))
                for item in candidates
            ),
        )
        return self.sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=candidates,
                select=select,
                prompt=OutboundMessage.from_text(prompt),
                labels=tuple(item.name for item in candidates),
            ),
        )

    async def _result_menu(
        self,
        context: MessageInputContext,
        actor: ActorRef | None,
        result: LuckySkinWindowResult,
    ) -> OutboundMessage:
        choices = self.service.detail_choices(result)
        result_message = await self.service.result_message(result, actor=actor)
        if not choices:
            return result_message

        async def select(
            choice: QueryChoice[PetImageSelection],
            _context: MessageInputContext,
        ) -> OutboundMessage:
            selected = await self.pet.select_image(choice.value)
            if selected.reply is not None:
                return selected.reply.to_outbound()
            if selected.message:
                return OutboundMessage.from_text(selected.message)
            return OutboundMessage.from_text("❌ 皮肤详情暂时不可用。")

        return self.sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=choices,
                select=select,
                prompt=result_message,
                labels=tuple(choice.name for choice in choices),
            ),
        )


def _access_error(
    error: LuckySkinWindowNotConfiguredError | LuckySkinWindowBindingError,
    *,
    query: bool,
) -> str:
    if isinstance(error, LuckySkinWindowNotConfiguredError):
        return "❌ 当前关联的数字账号未配置幸运橱窗。"
    action = "查询" if query else "管理橱窗关注"
    return f"❌ 请先绑定 TOML 指定的米米号 {error.args[0]} 后再{action}。"
