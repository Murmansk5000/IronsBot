from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest
from qqbot_agent_sdk.dto import QQMessageType

from ironsbot.core.outbound import DeliveryFailureKind, OutboundMessage
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.qq_official.message_rendering import (
    QQOfficialImagePayload,
    QQOfficialTextPayload,
)
from ironsbot.integrations.qq_official.outbound_messenger import (
    QQOfficialOutboundMessenger,
    QQOfficialUncertainDeliveryError,
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


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["group", "c2c"])
@pytest.mark.parametrize("value", [None, "", "  ", 123, False, {}, []])
async def test_invalid_send_receipt_is_uncertain(
    scope: str,
    value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = AsyncMock(return_value={"id": value})
    monkeypatch.setattr(_FakeApi, f"post_{scope}_message", post)
    client = _client(_FakeApi())
    send = client.send_to_group if scope == "group" else client.send_to_c2c

    with pytest.raises(QQOfficialUncertainDeliveryError, match="no message id"):
        await send("target", (QQOfficialTextPayload("result"),))

    assert post.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["group", "c2c"])
@pytest.mark.parametrize("value", [None, "", "  ", 123, False, {}, []])
async def test_invalid_upload_receipt_does_not_send_media(
    scope: str,
    value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = AsyncMock(return_value={"file_info": value})
    monkeypatch.setattr(_FakeApi, f"upload_{scope}_file", upload)
    api = _FakeApi()
    client = _client(api)
    send = client.send_to_group if scope == "group" else client.send_to_c2c

    with pytest.raises(RuntimeError, match="no file_info"):
        await send("target", (QQOfficialImagePayload(content=b"image"),))

    assert api.messages == []
    assert upload.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["group", "c2c"])
@pytest.mark.parametrize("stage", ["upload", "post", "receipt"])
async def test_partial_delivery_preserves_cause_and_stops_remaining_payloads(
    scope: str,
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = RuntimeError("429 rate limit")
    post = AsyncMock(
        side_effect=[
            {"id": "first"},
            error if stage == "post" else {"id": None},
        ]
    )
    monkeypatch.setattr(_FakeApi, f"post_{scope}_message", post)
    if stage == "upload":
        monkeypatch.setattr(
            _FakeApi, f"upload_{scope}_file", AsyncMock(side_effect=error)
        )
    client = _client(_FakeApi())
    send = client.send_to_group if scope == "group" else client.send_to_c2c

    with pytest.raises(QQOfficialUncertainDeliveryError, match="1/3") as caught:
        await send(
            "target",
            (
                QQOfficialTextPayload("before"),
                QQOfficialImagePayload(content=b"image"),
                QQOfficialTextPayload("after"),
            ),
        )

    assert post.await_count == (1 if stage == "upload" else 2)
    assert caught.value.__cause__ is not None
    if stage != "receipt":
        assert caught.value.__cause__ is error


@pytest.mark.asyncio
async def test_cancellation_after_partial_delivery_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = AsyncMock(side_effect=[{"id": "first"}, asyncio.CancelledError()])
    monkeypatch.setattr(_FakeApi, "post_group_message", post)
    payloads = (QQOfficialTextPayload("before"), QQOfficialTextPayload("after"))

    with pytest.raises(asyncio.CancelledError):
        await _client(_FakeApi()).send_to_group("target", payloads)

    assert post.await_count == len(payloads)


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["group", "c2c"])
@pytest.mark.parametrize("response", [None, [], "invalid", ValueError("invalid JSON")])
async def test_malformed_post_response_is_uncertain(
    scope: str,
    response: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = (
        AsyncMock(side_effect=response)
        if isinstance(response, Exception)
        else AsyncMock(return_value=response)
    )
    monkeypatch.setattr(_FakeApi, f"post_{scope}_message", post)
    client = _client(_FakeApi())
    messenger = QQOfficialOutboundMessenger({"app": True}, lambda _: client)
    target = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group" if scope == "group" else "private",
        "openid",
        account_id="app",
    )

    result = await messenger.send(target, OutboundMessage.from_text("result"))

    assert result.failure_kind is DeliveryFailureKind.UNCERTAIN
    assert post.await_count == 1


@pytest.mark.asyncio
async def test_first_post_rate_limit_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = AsyncMock(side_effect=RuntimeError("QQ Bot API error [429]"))
    monkeypatch.setattr(_FakeApi, "post_group_message", post)
    client = _client(_FakeApi())
    messenger = QQOfficialOutboundMessenger({"app": True}, lambda _: client)
    target = ConversationRef(Platform.QQ_OFFICIAL, "group", "openid", account_id="app")

    result = await messenger.send(target, OutboundMessage.from_text("result"))

    assert result.failure_kind is DeliveryFailureKind.RETRYABLE
    assert post.await_count == 1
