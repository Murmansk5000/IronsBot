# SPDX-License-Identifier: MIT
"""Thin Tencent SDK sender owned by one QQ Official AppID."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from qqbot_agent_sdk.dto import (
    MarkdownContent,
    MediaInfo,
    MessageReference,
    MessageToCreate,
    QQMessageType,
)
from qqbot_agent_sdk.media_loader import (
    UploadDailyLimitExceededError,
    UploadFileTooLargeError,
)

from ironsbot.integrations.qq_official.api_errors import (
    QQOfficialPartialDeliveryError,
)
from ironsbot.integrations.qq_official.message_rendering import (
    QQOfficialImagePayload,
    QQOfficialPayload,
    QQOfficialTextPayload,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Literal

    from qqbot_agent_sdk.api_client import QQApiClient
    from qqbot_agent_sdk.dto import InlineKeyboard

    from ironsbot.core.interactive_prompts import PromptSession
    from ironsbot.integrations.qq_official.media_upload import QQOfficialMediaUpload
    from ironsbot.integrations.qq_official.token_lifecycle import (
        QQOfficialTokenObserver,
    )

_MAX_KEYBOARD_ROWS = 5
_MAX_BUTTONS_PER_ROW = 5
_MAX_KEYBOARD_CHOICES = _MAX_KEYBOARD_ROWS * _MAX_BUTTONS_PER_ROW
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QQOfficialSendReceipt:
    id: str


@dataclass(slots=True)
class TencentQQClient:
    """Convert rendered operations to the official SDK's REST DTOs."""

    api: QQApiClient
    media: QQOfficialMediaUpload
    custom_keyboards: bool = False
    token_observer: QQOfficialTokenObserver | None = None

    async def send_to_c2c(
        self,
        openid: str,
        payloads: tuple[QQOfficialPayload, ...],
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> QQOfficialSendReceipt:
        return await self._send("c2c", openid, payloads, msg_id, msg_seq)

    async def send_to_group(
        self,
        group_openid: str,
        payloads: tuple[QQOfficialPayload, ...],
        msg_id: str | None = None,
        msg_seq: int | None = None,
    ) -> QQOfficialSendReceipt:
        return await self._send("group", group_openid, payloads, msg_id, msg_seq)

    async def _send(
        self,
        scope: Literal["c2c", "group"],
        target_id: str,
        payloads: tuple[QQOfficialPayload, ...],
        message_id: str | None,
        first_sequence: int | None,
    ) -> QQOfficialSendReceipt:
        first_id: str | None = None
        for offset, payload in enumerate(payloads):
            sequence = (
                first_sequence + offset
                if first_sequence is not None
                else max(1, self.api.next_msg_seq())
            )
            try:
                response = await self._send_payload(
                    scope,
                    target_id,
                    payload,
                    message_id=message_id,
                    sequence=sequence,
                )
                sent_id = _response_id(response)
            except Exception as error:
                if first_id is not None:
                    raise QQOfficialPartialDeliveryError(first_id) from error
                raise
            finally:
                if self.token_observer is not None:
                    self.token_observer.observe(self.api.access_token)
            logger.info(
                "QQ Official payload delivered: scope=%s mode=%s sequence=%s "
                "payload=%s",
                scope,
                "passive" if message_id is not None else "proactive",
                sequence,
                type(payload).__name__,
            )
            if first_id is None:
                first_id = sent_id
        if first_id is None:
            msg = "QQ Official message rendered no send operations"
            raise RuntimeError(msg)
        return QQOfficialSendReceipt(first_id)

    async def _send_payload(
        self,
        scope: Literal["c2c", "group"],
        target_id: str,
        payload: QQOfficialPayload,
        *,
        message_id: str | None,
        sequence: int,
    ) -> Mapping[str, object]:
        keyboard: InlineKeyboard | None = None
        if isinstance(payload, QQOfficialTextPayload):
            message = _text_message(
                payload,
                message_id=message_id,
                sequence=sequence,
            )
            if self.custom_keyboards and payload.prompt is not None:
                keyboard = _prompt_keyboard(payload.prompt)
        elif isinstance(payload, QQOfficialImagePayload):
            try:
                file_info = await self.media.upload_image(scope, target_id, payload)
            except UploadFileTooLargeError as error:
                logger.warning(
                    "QQ Official image exceeds platform limit: target_scope=%s "
                    "file_size=%s limit=%s",
                    scope,
                    error.file_size,
                    error.limit_bytes,
                )
                message = _media_fallback_message(
                    "图片超过 QQ 官方平台大小限制，暂时无法发送。",
                    message_id=message_id,
                    sequence=sequence,
                )
            except UploadDailyLimitExceededError as error:
                logger.warning(
                    "QQ Official daily media quota exhausted: target_scope=%s "
                    "file_size=%s",
                    scope,
                    error.file_size,
                )
                message = _media_fallback_message(
                    "机器人今日图片上传额度已用完，请稍后再试。",
                    message_id=message_id,
                    sequence=sequence,
                )
            else:
                message = MessageToCreate(
                    msg_type=QQMessageType.RICH_MEDIA,
                    msg_id=message_id or "",
                    msg_seq=sequence,
                    media=MediaInfo(file_info=file_info),
                )
        else:  # pragma: no cover - closed union guarded by renderer tests
            msg = f"Unsupported QQ Official payload: {type(payload).__name__}"
            raise TypeError(msg)
        _attach_message_reference(message, payload, message_id=message_id)
        if scope == "group":
            if keyboard is None:
                return await self.api.post_group_message(target_id, message)
            return await self.api.post_group_message(
                target_id,
                message,
                keyboard=keyboard,
            )
        if keyboard is None:
            return await self.api.post_c2c_message(target_id, message)
        return await self.api.post_c2c_message(
            target_id,
            message,
            keyboard=keyboard,
        )


def _text_message(
    payload: QQOfficialTextPayload,
    *,
    message_id: str | None,
    sequence: int,
) -> MessageToCreate:
    if payload.markdown:
        return MessageToCreate(
            msg_type=QQMessageType.MARKDOWN,
            msg_id=message_id or "",
            msg_seq=sequence,
            markdown=MarkdownContent(content=payload.content),
        )
    return MessageToCreate(
        content=payload.content,
        msg_type=QQMessageType.TEXT,
        msg_id=message_id or "",
        msg_seq=sequence,
    )


def _response_id(response: Mapping[str, object]) -> str:
    value = str(response.get("id", "")).strip()
    if not value:
        msg = "QQ Official send response returned no message id"
        raise RuntimeError(msg)
    return value


def _attach_message_reference(
    message: MessageToCreate,
    payload: QQOfficialPayload,
    *,
    message_id: str | None,
) -> None:
    if payload.reference_id is None:
        return
    if message_id is None:
        msg = "QQ Official source references require a passive reply"
        raise ValueError(msg)
    message.message_reference = MessageReference(message_id=payload.reference_id)


def _media_fallback_message(
    content: str,
    *,
    message_id: str | None,
    sequence: int,
) -> MessageToCreate:
    return MessageToCreate(
        content=content,
        msg_type=QQMessageType.TEXT,
        msg_id=message_id or "",
        msg_seq=sequence,
    )


@dataclass(frozen=True, slots=True)
class _PromptKeyboard:
    prompt: PromptSession

    def to_dict(self) -> dict[str, object]:
        buttons = [
            {
                "id": choice.id,
                "render_data": {
                    "label": choice.label,
                    "visited_label": choice.label,
                    "style": 1,
                },
                "action": {
                    "type": 2,
                    "permission": {
                        "type": 0,
                        "specify_user_ids": [self.prompt.actor.id],
                    },
                    "data": self.prompt.action_data(choice),
                    "reply": True,
                    "enter": True,
                    "unsupport_tips": "请发送对应序号",
                },
            }
            for choice in self.prompt.choices
        ]
        return {
            "content": {
                "rows": [
                    {"buttons": buttons[index : index + _MAX_BUTTONS_PER_ROW]}
                    for index in range(0, len(buttons), _MAX_BUTTONS_PER_ROW)
                ]
            }
        }


def _prompt_keyboard(prompt: PromptSession) -> InlineKeyboard | None:
    if len(prompt.choices) > _MAX_KEYBOARD_CHOICES:
        return None
    return cast("InlineKeyboard", _PromptKeyboard(prompt))
