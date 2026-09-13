# SPDX-License-Identifier: MIT
"""Portable operations for configured text and image commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.core.outbound import OutboundMessage
from ironsbot.services.messaging.sendpic import (
    ImageIndexOutOfRangeError,
    ImageNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.config.models.messaging import MessageReplyAction
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.messaging import PicConfig
    from ironsbot.services.messaging.sendpic import SendpicService
    from ironsbot.services.messaging.service import MessagingService
    from ironsbot.services.portable_reply import PortableOperation

IMAGE_MISSING_MESSAGE = "图片文件不存在，请检查机器人图片目录。"


def build_portable_messaging_operations(
    messaging: MessagingService,
) -> Mapping[str, PortableOperation]:
    """Expose configured text commands whose semantics are platform-neutral."""

    return {
        f"messaging.{action.id}": _text_operation(action)
        for action in messaging.portable_command_actions
    }


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
