# SPDX-License-Identifier: MIT
"""Portable Autocard and sanctuary query interactions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.outbound import (
    BinaryImagePart,
    OutboundMessage,
    RemoteImagePart,
)
from ironsbot.services.portable_query_sessions import PortableMenuSpec
from ironsbot.services.portable_reply import PortableReply
from ironsbot.services.seer.autocard_sanctuary import format_sanctuary_overview
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.portable_query_sessions import PortableQuerySessions
    from ironsbot.services.portable_reply import PortableOperation
    from ironsbot.services.seer.autocard import (
        AutocardEntry,
        AutocardPromptValue,
        AutocardService,
    )
    from ironsbot.services.seer.autocard_media import AutocardMediaService
    from ironsbot.services.seer.autocard_sanctuary import (
        AutocardSanctuaryService,
        SanctuaryPromptValue,
        SanctuarySearchResult,
    )


def build_portable_autocard_operations(
    service: AutocardService,
    media: AutocardMediaService,
    sanctuary: AutocardSanctuaryService,
    sessions: PortableQuerySessions,
) -> Mapping[str, PortableOperation]:
    owner = _PortableAutocardOperations(service, media, sanctuary, sessions)
    return {
        "seer.autocard.query": owner.query,
        "seer.autocard.sanctuary": owner.query_sanctuary,
    }


@dataclass(frozen=True, slots=True)
class _PortableAutocardOperations:
    service: AutocardService
    media: AutocardMediaService
    sanctuary: AutocardSanctuaryService
    sessions: PortableQuerySessions

    async def query(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage | PortableReply:
        try:
            result = self.service.search(text)
        except (DataUnavailableError, RuntimeError) as error:
            return _service_error("群星牌公开配置", error)
        if result.entry is not None:
            return await _autocard_reply(self.media, result.entry)
        if result.message:
            return OutboundMessage.from_text(result.message)
        if not result.prompt_values:
            return OutboundMessage.from_text("❌ 未找到对应群星牌资料。")

        async def select(
            value: AutocardPromptValue,
        ) -> OutboundMessage | PortableReply:
            try:
                entry = self.service.select(value)
            except (DataUnavailableError, RuntimeError) as error:
                return _service_error("群星牌公开配置", error)
            if entry is None:
                return OutboundMessage.from_text(
                    "❌ 未找到该群星牌资料，这可能是数据库数据已更新或缺失。"
                )
            return await _autocard_reply(self.media, entry)

        return self.sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=result.prompt_values,
                select=select,
                prompt=OutboundMessage.from_text(result.prompt_text),
                keep_open=True,
                exit_message="❌ 已退出群星牌选择",
            ),
        )

    async def query_sanctuary(
        self,
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage:
        try:
            result = self.sanctuary.search(text)
        except (DataUnavailableError, RuntimeError) as error:
            return _service_error("群星牌场地公开配置", error)
        return self._present_sanctuary(context, result)

    def _present_sanctuary(
        self,
        context: MessageInputContext,
        result: SanctuarySearchResult,
    ) -> OutboundMessage:
        if result.message:
            return OutboundMessage.from_text(result.message)
        if result.effect is not None:
            return OutboundMessage.from_text(result.effect.text)
        if result.sanctuary is not None:
            values, prompt = format_sanctuary_overview(result.sanctuary)
            return self._offer_sanctuary(context, values, prompt)
        if result.prompt_values:
            return self._offer_sanctuary(
                context,
                result.prompt_values,
                result.prompt_text,
            )
        return OutboundMessage.from_text("❌ 未找到对应群星牌场地或祝印。")

    def _offer_sanctuary(
        self,
        context: MessageInputContext,
        values: tuple[SanctuaryPromptValue, ...],
        prompt: str,
    ) -> OutboundMessage:
        async def select(value: SanctuaryPromptValue) -> OutboundMessage:
            try:
                result = self.sanctuary.select(value)
            except (DataUnavailableError, RuntimeError) as error:
                return _service_error("群星牌场地公开配置", error)
            return self._present_sanctuary(context, result)

        return self.sessions.offer_menu(
            context,
            PortableMenuSpec(
                choices=values,
                select=select,
                prompt=OutboundMessage.from_text(prompt),
                keep_open=True,
                exit_message="❌ 已退出群星牌场地选择",
            ),
        )


def _service_error(label: str, error: Exception) -> OutboundMessage:
    return OutboundMessage.from_text(
        DATABASE_UNAVAILABLE_MESSAGE
        if isinstance(error, DataUnavailableError)
        else f"❌ {label}获取失败：{error}"
    )


async def _autocard_reply(
    media: AutocardMediaService,
    entry: AutocardEntry,
) -> OutboundMessage | PortableReply:
    message = await media.outbound(entry)
    fallback = (
        entry.to_outbound()
        if any(
            isinstance(part, (BinaryImagePart, RemoteImagePart))
            for part in message.parts
        )
        else None
    )
    return (
        message
        if fallback is None
        else PortableReply(message, fallback_message=fallback)
    )
