# SPDX-License-Identifier: MIT
"""Owner-only binding confirmation shared by independent player shortcuts."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.portable_reply import PortableReply

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.seer.player_id_resolver import (
        PlayerIdResolver,
        PlayerTargetSource,
    )
    from ironsbot.services.seer.player_service import PlayerService
    from ironsbot.services.seer.player_service_models import PlayerQueryResult


logger = logging.getLogger(__name__)


def offer_profile_binding_confirmation(  # noqa: PLR0913 - frozen query and owner policy
    service: PlayerService,
    sessions: PortableQuerySessions,
    context: MessageInputContext,
    result: PlayerQueryResult,
    prepare: Callable[[PlayerQueryResult, MessageInputContext], PortableReply],
    *,
    validate: Callable[[MessageInputContext], str | None],
    explicit: bool,
) -> PortableReply:
    pending = result.pending
    assert pending is not None
    expected = result.binding_replacement or service.binding_state(
        context.message.actor
    )

    async def confirm(
        choice: Literal["confirm", "keep"], selected: MessageInputContext
    ) -> PortableReply:
        error = validate(selected)
        if error:
            return PortableReply(
                OutboundMessage.from_text(error, request_succeeded=False)
            )
        if explicit and choice == "keep":
            return PortableReply(OutboundMessage.from_text("已取消绑定。"))
        saved = service.save_binding_choice(
            selected.message.actor,
            pending,
            accepted=choice == "confirm",
            replacing_existing=result.binding_replacement is not None,
            expected_binding=expected,
        )
        if not saved.succeeded:
            return PortableReply(
                OutboundMessage.from_text(saved.message, request_succeeded=False)
            )
        reply = prepare(
            replace(result, offer_binding=False, binding_replacement=None), selected
        )
        return binding_receipt(service, selected, reply) if saved.changed else reply

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
                        actor=context.message.actor,
                    )
                ),
                labels=("确认绑定", "不绑定"),
                text_inputs=(
                    frozenset({"是", "y", "yes", "确认", "确定"}),
                    frozenset({"否", "n", "no", "取消"}),
                ),
                invalid_choice_message="请回复“是”或“否”，或输入 0 退出。",
                exit_message="已退出绑定选择。",
            ),
        )
    )


def binding_access_error(  # noqa: PLR0913 - existing policy context
    features: FeatureService,
    resolver: PlayerIdResolver,
    context: MessageInputContext,
    player_id: int,
    source: PlayerTargetSource,
    *,
    binding_command: bool = False,
) -> str | None:
    if not features.is_feature_allowed(
        context.message.actor, context.message.conversation, "seer_player"
    ):
        return "该功能当前未对你开放。"
    return (
        None
        if binding_command
        else resolver.query_access_error(context.message.actor, player_id, source)
    )


async def confirm_shortcut_binding(  # noqa: PLR0913 - shared binding plus target access
    service: PlayerService,
    sessions: PortableQuerySessions,
    player_id: int,
    context: MessageInputContext,
    query: Callable[[int, MessageInputContext], Awaitable[PortableReply | None]],
    *,
    validate: Callable[[MessageInputContext], str | None],
) -> PortableReply | None:
    if (
        context.has_member_mentions
        or not context.offer_player_binding
        or not service.should_offer_binding(context.message.actor)
    ):
        return await query(player_id, context)
    expected = service.binding_state(context.message.actor)

    async def confirm(
        choice: Literal["confirm", "skip"], selected: MessageInputContext
    ) -> PortableReply | None:
        error = validate(selected)
        if error:
            return PortableReply(
                OutboundMessage.from_text(error, request_succeeded=False)
            )
        bound = False
        if choice == "confirm":
            saved = service.bind_shortcut_target(
                selected.message.actor,
                player_id,
                expected_binding=expected,
            )
            if not saved.succeeded:
                return PortableReply(
                    OutboundMessage.from_text(saved.message, request_succeeded=False)
                )
            bound = saved.changed
        else:
            service.decline_binding_offer(selected.message.actor)
        try:
            reply = await query(player_id, selected)
        except Exception:
            if not bound:
                raise
            logger.exception("绑定后的快捷查询失败")
            reply = None
        return (
            binding_receipt(service, selected, binding_query_reply(reply, player_id))
            if bound
            else reply
        )

    return PortableReply(
        sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=("confirm", "skip"),
                choice_keys=("confirm", "skip"),
                labels=("确认绑定", "不绑定"),
                select=confirm,
                text_inputs=(
                    frozenset({"是", "y", "yes"}),
                    frozenset({"否", "n", "no"}),
                ),
                prompt=OutboundMessage.from_text(
                    service.shortcut_binding_offer(
                        player_id, actor=context.message.actor
                    )
                ),
                exit_message="已退出查询。",
            ),
        )
    )


def binding_receipt(
    service: PlayerService, context: MessageInputContext, reply: PortableReply
) -> PortableReply:
    """Keep acknowledgement delivery separate from query receipts and charging."""

    async def result() -> PortableReply:
        return reply

    return PortableReply(
        OutboundMessage.from_text(
            service.binding_success_notice(context.message.actor)
        ),
        initial_is_advisory=True,
        continuation=result,
    )


def binding_query_reply(reply: PortableReply | None, player_id: int) -> PortableReply:
    """Annotate failed final replies without announcing a successful binding."""
    presenter = _BoundQueryReply(reply, player_id)
    return presenter.prepare()


@dataclass(frozen=True, slots=True)
class _BoundQueryReply:
    original: PortableReply | None
    player_id: int

    @property
    def failure_text(self) -> str:
        return f"米米号{self.player_id}绑定已生效，但本次查询未能完整返回。"

    def message(self, value: OutboundMessage) -> OutboundMessage:
        if value.request_succeeded:
            return value
        return replace(
            value, parts=(TextPart(self.failure_text + "\n\n"), *value.parts)
        )

    async def follow_up(self) -> OutboundMessage:
        assert self.original is not None and self.original.follow_up is not None
        try:
            return self.message(await self.original.follow_up())
        except Exception as error:  # noqa: BLE001 - binding is already committed
            logger.warning("绑定后后续查询中断：%s", type(error).__name__)
            return await self.on_error(error)

    async def continuation(self) -> PortableReply:
        assert self.original is not None and self.original.continuation is not None
        try:
            return binding_query_reply(
                await self.original.continuation(), self.player_id
            )
        except Exception as error:  # noqa: BLE001 - binding is already committed
            logger.warning("绑定后延迟查询中断：%s", type(error).__name__)
            return PortableReply(await self.on_error(error))

    async def on_error(self, error: Exception) -> OutboundMessage:
        assert self.original is not None
        if self.original.on_operation_error is not None:
            return self.message(
                replace(
                    await self.original.on_operation_error(error),
                    request_succeeded=False,
                )
            )
        return OutboundMessage.from_text(self.failure_text, request_succeeded=False)

    async def stream(self) -> AsyncGenerator[OutboundMessage, None]:
        assert self.original is not None and self.original.additional_stream is not None
        try:
            async for part in self.original.additional_stream():
                yield self.message(part)
        except Exception as error:  # noqa: BLE001 - binding is already committed
            logger.warning("绑定后流式查询中断：%s", type(error).__name__)
            yield await self.on_error(error)

    def prepare(self) -> PortableReply:
        original = self.original
        if original is None:
            return PortableReply(
                OutboundMessage.from_text(self.failure_text, request_succeeded=False)
            )
        return replace(
            original,
            message=self.message(original.message),
            additional_messages=tuple(map(self.message, original.additional_messages)),
            follow_up=self.follow_up if original.follow_up else None,
            continuation=self.continuation if original.continuation else None,
            additional_stream=self.stream if original.additional_stream else None,
            on_operation_error=self.on_error,
        )
