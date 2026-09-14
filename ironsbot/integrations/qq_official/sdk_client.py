# SPDX-License-Identifier: MIT
"""Thin Tencent SDK sender owned by one QQ Official AppID."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from qqbot_agent_sdk.constants import MEDIA_TYPE_IMAGE
from qqbot_agent_sdk.dto import (
    MediaInfo,
    MessageToCreate,
    QQMessageType,
    RichMediaMessage,
)

from ironsbot.integrations.qq_official.message_rendering import (
    QQOfficialImagePayload,
    QQOfficialPayload,
    QQOfficialTextPayload,
)
from ironsbot.integrations.qq_official.outbound_messenger import (
    QQOfficialUncertainDeliveryError,
)

if TYPE_CHECKING:
    from qqbot_agent_sdk.api_client import QQApiClient


@dataclass(frozen=True, slots=True)
class QQOfficialSendReceipt:
    id: str


@dataclass(slots=True)
class TencentQQClient:
    """Convert rendered operations to the official SDK's REST DTOs."""

    api: QQApiClient

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
        scope: str,
        target_id: str,
        payloads: tuple[QQOfficialPayload, ...],
        message_id: str | None,
        first_sequence: int | None,
    ) -> QQOfficialSendReceipt:
        first_id: str | None = None
        for offset, payload in enumerate(payloads):
            try:
                sequence = (
                    first_sequence + offset
                    if first_sequence is not None
                    else max(1, self.api.next_msg_seq())
                )
                response = await self._send_payload(
                    scope,
                    target_id,
                    payload,
                    message_id=message_id,
                    sequence=sequence,
                )
                sent_id = _response_id(response)
            except Exception as error:
                if first_id is None:
                    raise
                msg = (
                    f"QQ Official partial delivery: {offset}/{len(payloads)} "
                    f"operations acknowledged; first message id={first_id}; "
                    f"next operation failed: {type(error).__name__}: {error}"
                )
                raise QQOfficialUncertainDeliveryError(msg) from error
            if first_id is None:
                first_id = sent_id
        if first_id is None:
            msg = "QQ Official message rendered no send operations"
            raise RuntimeError(msg)
        return QQOfficialSendReceipt(first_id)

    async def _send_payload(
        self,
        scope: str,
        target_id: str,
        payload: QQOfficialPayload,
        *,
        message_id: str | None,
        sequence: int,
    ) -> Mapping[str, object]:
        if isinstance(payload, QQOfficialTextPayload):
            message = MessageToCreate(
                content=payload.content,
                msg_type=QQMessageType.TEXT,
                msg_id=message_id or "",
                msg_seq=sequence,
            )
        elif isinstance(payload, QQOfficialImagePayload):
            file_info = await self._upload_image(scope, target_id, payload)
            message = MessageToCreate(
                msg_type=QQMessageType.RICH_MEDIA,
                msg_id=message_id or "",
                msg_seq=sequence,
                media=MediaInfo(file_info=file_info),
            )
        else:  # pragma: no cover - closed union guarded by renderer tests
            msg = f"Unsupported QQ Official payload: {type(payload).__name__}"
            raise TypeError(msg)
        try:
            if scope == "group":
                return await self.api.post_group_message(target_id, message)
            return await self.api.post_c2c_message(target_id, message)
        except ValueError as error:
            msg = "QQ Official send returned an invalid response"
            raise QQOfficialUncertainDeliveryError(msg) from error

    async def _upload_image(
        self,
        scope: str,
        target_id: str,
        payload: QQOfficialImagePayload,
    ) -> str:
        upload = RichMediaMessage(
            file_type=MEDIA_TYPE_IMAGE,
            url=payload.url or "",
            file_data=(
                base64.b64encode(payload.content).decode("ascii")
                if payload.content is not None
                else ""
            ),
            file_name=payload.filename,
            srv_send_msg=False,
        )
        response = (
            await self.api.upload_group_file(target_id, upload)
            if scope == "group"
            else await self.api.upload_c2c_file(target_id, upload)
        )
        value = response.get("file_info")
        file_info = value.strip() if isinstance(value, str) else ""
        if not file_info:
            msg = "QQ Official image upload returned no file_info"
            raise RuntimeError(msg)
        return file_info


def _response_id(response: object) -> str:
    raw = response.get("id") if isinstance(response, Mapping) else None
    value = raw.strip() if isinstance(raw, str) else ""
    if not value:
        msg = "QQ Official send response returned no message id"
        raise QQOfficialUncertainDeliveryError(msg)
    return value
