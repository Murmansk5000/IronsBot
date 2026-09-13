# SPDX-License-Identifier: MIT
"""Portable operations for configured text and image commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.authorization import GROUP_MANAGER_ROLES
from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.messaging.sendpic import (
    ImageIndexOutOfRangeError,
    ImageNotFoundError,
)
from ironsbot.services.portable_query_sessions import PortableMenuSpec

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from ironsbot.config.models.messaging import MessageReplyAction
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.messaging import PicConfig
    from ironsbot.core.platform import ConversationRef
    from ironsbot.services.messaging.sendpic import SendpicService
    from ironsbot.services.messaging.service import MessagingService
    from ironsbot.services.messaging.subscriptions import PushSubscriptionOption
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation

IMAGE_MISSING_MESSAGE = "图片文件不存在，请检查机器人图片目录。"


def build_portable_messaging_operations(
    messaging: MessagingService,
    sessions: PortableQuerySessions,
) -> Mapping[str, PortableOperation]:
    """Expose configured text commands whose semantics are platform-neutral."""

    operations = {
        f"messaging.{action.id}": _text_operation(action)
        for action in messaging.portable_command_actions
    }
    operations["messaging.push_subscription"] = _subscription_operation(
        messaging,
        sessions,
    )
    return operations


def _subscription_operation(
    messaging: MessagingService,
    sessions: PortableQuerySessions,
) -> PortableOperation:
    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        message = context.message
        read_only = message.conversation.kind == "group" and not (
            message.group_role in GROUP_MANAGER_ROLES
            or messaging.feature_policy.is_actor_superuser(message.actor)
        )
        return await _PortableSubscriptionMenus(
            messaging,
            sessions,
            context,
        ).root(read_only=read_only)

    return execute


@dataclass(frozen=True, slots=True)
class _PortableSubscriptionMenus:
    messaging: MessagingService
    sessions: PortableQuerySessions
    context: MessageInputContext

    @property
    def conversation(self) -> ConversationRef:
        return self.context.message.conversation

    async def root(
        self,
        *,
        read_only: bool,
        notice: str | None = None,
    ) -> OutboundMessage:
        options, prompt = await self.messaging.prepared_subscription_menu(
            self.conversation,
            read_only=read_only,
        )
        if not options:
            return OutboundMessage.from_text("当前没有可管理的推送订阅。")

        async def select(option: PushSubscriptionOption) -> OutboundMessage:
            if read_only:
                return await self.root(
                    read_only=True,
                    notice="普通群成员只能查看本群推送订阅，不能修改。",
                )
            submenu = self.messaging.subscription_submenu(
                self.conversation,
                option,
                read_only=False,
            )
            if submenu is not None:
                submenu_options, submenu_prompt = submenu
                return self.submenu(option, submenu_options, submenu_prompt)
            result = self.messaging.toggle_subscription(self.conversation, option)
            return await self.root(read_only=False, notice=result)

        return self._install(options, select, prompt, notice)

    def submenu(
        self,
        parent: PushSubscriptionOption,
        options: list[PushSubscriptionOption],
        prompt: str,
        notice: str | None = None,
    ) -> OutboundMessage:
        async def select(option: PushSubscriptionOption) -> OutboundMessage:
            result = self.messaging.toggle_subscription(self.conversation, option)
            refreshed = self.messaging.subscription_submenu(
                self.conversation,
                parent,
                read_only=False,
            )
            if refreshed is None:
                return await self.root(read_only=False, notice=result)
            refreshed_options, refreshed_prompt = refreshed
            return self.submenu(
                parent,
                refreshed_options,
                refreshed_prompt,
                result,
            )

        return self._install(options, select, prompt, notice)

    def _install(
        self,
        options: list[PushSubscriptionOption],
        select: Callable[[PushSubscriptionOption], Awaitable[OutboundMessage]],
        prompt: str,
        notice: str | None,
    ) -> OutboundMessage:
        self.sessions.offer_menu(
            self.context,
            PortableMenuSpec(
                choices=tuple(options),
                select=select,
                prompt=OutboundMessage.from_text(prompt),
            ),
        )
        return OutboundMessage.from_text(_menu_with_notice(prompt, notice))


def _menu_with_notice(prompt: str, notice: str | None) -> str:
    return prompt if notice is None else f"{notice}\n\n{prompt}"


def build_portable_sendpic_operations(
    service: SendpicService,
) -> Mapping[str, PortableOperation]:
    """Expose configured image commands through their shared image service."""

    return {
        f"sendpic.{config.id}": _image_operation(service, config)
        for config in service.commands
    }


def _text_operation(action: MessageReplyAction) -> PortableOperation:
    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text, context
        return OutboundMessage.from_text(action.message)

    return execute


def _image_operation(
    service: SendpicService,
    config: PicConfig,
) -> PortableOperation:
    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        del text
        if config.mode == "single":
            try:
                result = await service.fetch_single(config)
            except ImageNotFoundError:
                return OutboundMessage.from_text(IMAGE_MISSING_MESSAGE)
            return result.to_outbound()

        request = service.parse_indexed(context.text)
        if request is None or request.command_id != config.id:
            msg = f"catalog accepted input rejected by sendpic parser: {context.text!r}"
            raise ValueError(msg)
        try:
            result = await service.fetch_indexed(config, request.index)
        except ImageIndexOutOfRangeError as exc:
            return OutboundMessage.from_text(str(exc))
        return result.to_outbound(config.message_template, command=config.command)

    return execute
