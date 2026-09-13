from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest
from qqbot_agent_sdk.dto import QQMessageType

from ironsbot.integrations.qq_official.message_rendering import (
    QQOfficialImagePayload,
    QQOfficialTextPayload,
)
from ironsbot.integrations.qq_official.sdk_client import TencentQQClient

if TYPE_CHECKING:
    from qqbot_agent_sdk.api_client import QQApiClient
    from qqbot_agent_sdk.dto import MessageToCreate, RichMediaMessage

PASSIVE_SEQUENCE = 3


@dataclass(slots=True)
class _FakeApi:
    sequence: int = 0
    messages: list[tuple[str, str, MessageToCreate]] = field(default_factory=list)
    uploads: list[tuple[str, str, RichMediaMessage]] = field(default_factory=list)

    def next_msg_seq(self) -> int:
        self.sequence += 1
        return self.sequence

    async def post_group_message(
        self,
        target: str,
        message: MessageToCreate,
    ) -> dict[str, object]:
        self.messages.append(("group", target, message))
        return {"id": f"message-{len(self.messages)}"}

    async def post_c2c_message(
        self,
        target: str,
        message: MessageToCreate,
    ) -> dict[str, object]:
        self.messages.append(("c2c", target, message))
        return {"id": f"message-{len(self.messages)}"}

    async def upload_group_file(
        self,
        target: str,
        upload: RichMediaMessage,
    ) -> dict[str, object]:
        self.uploads.append(("group", target, upload))
        return {"file_info": "group-file"}

    async def upload_c2c_file(
        self,
        target: str,
        upload: RichMediaMessage,
    ) -> dict[str, object]:
        self.uploads.append(("c2c", target, upload))
        return {"file_info": "c2c-file"}


def _client(api: _FakeApi) -> TencentQQClient:
    return TencentQQClient(cast("QQApiClient", api))


@pytest.mark.asyncio
async def test_sdk_client_sends_text_with_passive_reply_identity() -> None:
    api = _FakeApi()

    receipt = await _client(api).send_to_group(
        "group-openid",
        (QQOfficialTextPayload("result"),),
        msg_id="incoming-id",
        msg_seq=PASSIVE_SEQUENCE,
    )

    message = api.messages[0][2]
    assert receipt.id == "message-1"
    assert api.messages[0][0:2] == ("group", "group-openid")
    assert message.content == "result"
    assert message.msg_type == QQMessageType.TEXT
    assert message.msg_id == "incoming-id"
    assert message.msg_seq == PASSIVE_SEQUENCE


@pytest.mark.asyncio
async def test_sdk_client_uploads_binary_image_before_sending_media() -> None:
    api = _FakeApi()

    await _client(api).send_to_c2c(
        "user-openid",
        (QQOfficialImagePayload(content=b"image", filename="preview.png"),),
    )

    upload = api.uploads[0][2]
    message = api.messages[0][2]
    assert api.uploads[0][0:2] == ("c2c", "user-openid")
    assert upload.file_data == "aW1hZ2U="
    assert upload.file_name == "preview.png"
    assert upload.srv_send_msg is False
    assert message.msg_type == QQMessageType.RICH_MEDIA
    assert message.media is not None
    assert message.media.file_info == "c2c-file"


@pytest.mark.asyncio
async def test_sdk_client_sends_multiple_payloads_with_consecutive_sequences() -> None:
    api = _FakeApi()

    await _client(api).send_to_group(
        "group-openid",
        (
            QQOfficialTextPayload("before"),
            QQOfficialImagePayload(url="https://example.invalid/image.png"),
            QQOfficialTextPayload("after"),
        ),
        msg_id="incoming-id",
        msg_seq=1,
    )

    assert [message.msg_seq for _, _, message in api.messages] == [1, 2, 3]
    assert [message.msg_id for _, _, message in api.messages] == [
        "incoming-id",
        "incoming-id",
        "incoming-id",
    ]
    assert api.uploads[0][2].url == "https://example.invalid/image.png"
