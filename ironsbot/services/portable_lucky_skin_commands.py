# SPDX-License-Identifier: MIT
"""Portable lucky-skin-window commands backed by the shared domain service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.commands import parse_confirmation
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.selection import SelectionMenuItem, format_selection_menu
from ironsbot.services.portable_query_sessions import (
    PortableMenuSpec,
    PortableTextInputSpec,
)
from ironsbot.services.portable_reply import PortableReply, progress_operation_reply
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE
from ironsbot.services.seer.lucky_skin_commands import (
    LUCKY_SKIN_WATCH_LIST_COMMANDS,
    LUCKY_SKIN_WATCH_REMOVE_COMMANDS,
    parse_lucky_skin_watch_target,
)
from ironsbot.services.seer.lucky_skin_window import (
    LuckySkinWindowBindingError,
    LuckySkinWindowError,
    LuckySkinWindowNotConfiguredError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation, ProgressReporter
    from ironsbot.services.seer.lucky_skin_window import (
        LuckySkinWatchItem,
        LuckySkinWindowResult,
        LuckySkinWindowService,
    )
    from ironsbot.services.seer.pet_query import PetImageSelection, PetQueryService
    from ironsbot.services.seer.query_result import QueryChoice

_QUERY_PROGRESS = "⏳ 幸运橱窗正在查询，完成后会直接发送结果。"
_ACCESS_ERRORS = (LuckySkinWindowNotConfiguredError, LuckySkinWindowBindingError)
logger = logging.getLogger(__name__)


def build_portable_lucky_skin_operations(
    service: LuckySkinWindowService,
    pet: PetQueryService,
    sessions: PortableQuerySessions,
) -> Mapping[str, PortableOperation]:
    """Bind every lucky-window command without assuming a numeric QQ identity."""

    owner = _PortableLuckySkinOperations(service, pet, sessions)
    return {
        "seer.lucky_skin_window.query": owner.query,
        "seer.lucky_skin_window.watch.list": owner.watch_list,
        "seer.lucky_skin_window.watch.add": owner.watch_add,
        "seer.lucky_skin_window.watch.remove": owner.watch_remove,
        "seer.lucky_skin_window.watch.clear": owner.watch_clear,
        "seer.lucky_skin_window.watch.reset": owner.watch_reset,
    }


@dataclass(frozen=True, slots=True)
class _PortableLuckySkinOperations:
    service: LuckySkinWindowService
    pet: PetQueryService
    sessions: PortableQuerySessions

    async def query(
        self,
        text: str,
        context: MessageInputContext,
    ) -> PortableReply | OutboundMessage:
        del text
        try:
            cached = self.service.cached_for_actor(context.message.actor)
        except _ACCESS_ERRORS as error:
            return _access_error(error, action="查询")
        if cached is not None:
            return await self._present_result(context, cached)
        return self.sessions.offer_text_input(
            context,
            PortableTextInputSpec(
                submit=partial(self._confirm_query, context=context),
                prompt=OutboundMessage.from_text(
                    "今日幸运橱窗尚未获取，需要登录查询。\n"
                    "是否继续？\n"
                    "回复“是”或“y”确认，回复“否”或“n”取消。"
                ),
                exit_message="已取消幸运橱窗查询。",
                accept=_is_confirmation,
            ),
        )

    async def _confirm_query(
        self,
        answer: str,
        *,
        context: MessageInputContext,
    ) -> PortableReply | OutboundMessage:
        if parse_confirmation(answer) is not True:
            return OutboundMessage.from_text("已取消幸运橱窗查询。")
        return await progress_operation_reply(
            partial(self._execute_query, context=context)
        )

    async def _execute_query(
        self,
        progress: ProgressReporter,
        *,
        context: MessageInputContext,
    ) -> OutboundMessage:
        await progress(_QUERY_PROGRESS)
        try:
            result = await self.service.check_for_actor(context.message.actor)
        except _ACCESS_ERRORS as error:
            return _access_error(error, action="查询")
        except TimeoutError:
            return OutboundMessage.from_text("❌ 幸运橱窗查询超时，稍后再试。")
        except LuckySkinWindowError:
            return OutboundMessage.from_text(
                "❌ 幸运橱窗数据暂时不可用，稍后再试。"
            )
        except Exception:
            logger.exception(
                "portable lucky skin window query failed: actor=%s",
                context.message.actor,
            )
            return OutboundMessage.from_text(
                "❌ 幸运橱窗查询失败，稍后再试。"
            )
        return await self._present_result(context, result)

    async def _present_result(
        self,
        context: MessageInputContext,
        result: LuckySkinWindowResult,
    ) -> OutboundMessage:
        async def select(
            choice: QueryChoice[PetImageSelection],
        ) -> OutboundMessage:
            try:
                selected = await self.pet.select_image(choice.value)
            except DataUnavailableError:
                return OutboundMessage.from_text(DATABASE_UNAVAILABLE_MESSAGE)
            if selected.reply is not None:
                return selected.reply.to_outbound()
            return OutboundMessage.from_text(
                selected.message or "❌ 皮肤详情暂时不可用。"
            )

        return self.sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=self.service.detail_choices(result),
                select=select,
                prompt=await self.service.result_message(
                    result,
                    actor=context.message.actor,
                ),
                exit_message="已退出幸运橱窗查询。",
            ),
        )

    async def watch_list(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        try:
            message = self.service.watch_list_message(context.message.actor)
        except _ACCESS_ERRORS as error:
            return _access_error(error, action="管理橱窗关注")
        return OutboundMessage.from_text(message)

    async def watch_add(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        return self._watch_change(
            context,
            _required_watch_argument(text, LUCKY_SKIN_WATCH_LIST_COMMANDS),
            watched=True,
        )

    async def watch_remove(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        return self._watch_change(
            context,
            _required_watch_argument(text, LUCKY_SKIN_WATCH_REMOVE_COMMANDS),
            watched=False,
        )

    def _watch_change(
        self,
        context: MessageInputContext,
        argument: str,
        *,
        watched: bool,
    ) -> OutboundMessage:
        actor = context.message.actor
        try:
            candidates = self.service.resolve_watch_candidates(actor, argument)
        except _ACCESS_ERRORS as error:
            return _access_error(error, action="管理橱窗关注")
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
        return self._watch_menu(context, candidates, watched=watched)

    def _watch_menu(
        self,
        context: MessageInputContext,
        candidates: tuple[LuckySkinWatchItem, ...],
        *,
        watched: bool,
    ) -> OutboundMessage:
        async def select(item: LuckySkinWatchItem) -> OutboundMessage:
            return OutboundMessage.from_text(
                self.service.watch_change_message(
                    context.message.actor,
                    item,
                    watched=watched,
                )
            )

        return self.sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=candidates,
                select=select,
                prompt=OutboundMessage.from_text(
                    format_selection_menu(
                        title="请问你想管理的皮肤是……",
                        items=tuple(
                            SelectionMenuItem(
                                label=item.name,
                                detail_lines=(item.identifiers,),
                            )
                            for item in candidates
                        ),
                    )
                ),
                exit_message="已退出橱窗关注管理。",
            ),
        )

    async def watch_clear(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        return _watch_simple(
            partial(self.service.watch_clear_message, context.message.actor)
        )

    async def watch_reset(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        return _watch_simple(
            partial(self.service.watch_reset_message, context.message.actor)
        )


def _watch_simple(operation: Callable[[], str]) -> OutboundMessage:
    try:
        message = operation()
    except _ACCESS_ERRORS as error:
        return _access_error(error, action="管理橱窗关注")
    return OutboundMessage.from_text(message)


def _access_error(
    error: LuckySkinWindowNotConfiguredError | LuckySkinWindowBindingError,
    *,
    action: str,
) -> OutboundMessage:
    if isinstance(error, LuckySkinWindowNotConfiguredError):
        return OutboundMessage.from_text("❌ 当前账号未配置幸运橱窗。")
    return OutboundMessage.from_text(
        f"❌ 先绑定配置指定的米米号 {error.args[0]}，再{action}。"
    )


def _required_watch_argument(text: str, commands: tuple[str, ...]) -> str:
    argument = parse_lucky_skin_watch_target(text, commands=commands)
    if argument is None:
        msg = f"catalog accepted lucky-window input without an argument: {text!r}"
        raise ValueError(msg)
    return argument


def _is_confirmation(answer: str) -> bool:
    return answer.strip() == "0" or parse_confirmation(answer) is not None
