from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest
from qqbot_agent_sdk.dto import QQMessageType
from qqbot_agent_sdk.media_loader import (
    UploadDailyLimitExceededError,
    UploadFileTooLargeError,
)

from ironsbot.core.interactive_prompts import PromptChoice, PromptSession
from ironsbot.core.outbound import OutboundMessage
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.qq_official.api_errors import (
    QQOfficialApiError,
    QQOfficialPartialDeliveryError,
)
from ironsbot.integrations.qq_official.message_rendering import (
    QQOfficialImagePayload,
    QQOfficialTextPayload,
    render_qq_official_outbound_message,
)
from ironsbot.integrations.qq_official.sdk_client import TencentQQClient

if TYPE_CHECKING:
    from qqbot_agent_sdk.api_client import QQApiClient
    from qqbot_agent_sdk.dto import InlineKeyboard, MessageToCreate

    from ironsbot.integrations.qq_official.media_upload import QQOfficialMediaUpload

PASSIVE_SEQUENCE = 3


@dataclass(slots=True)
class _FakeApi:
    sequence: int = 0
    messages: list[tuple[str, str, MessageToCreate]] = field(default_factory=list)
    keyboards: list[InlineKeyboard | None] = field(default_factory=list)

    def next_msg_seq(self) -> int:
        self.sequence += 1
        return self.sequence

    async def post_group_message(
        self,
        target: str,
        message: MessageToCreate,
        *,
        keyboard: InlineKeyboard | None = None,
    ) -> dict[str, object]:
        self.messages.append(("group", target, message))
        self.keyboards.append(keyboard)
        return {"id": f"message-{len(self.messages)}"}

    async def post_c2c_message(
        self,
        target: str,
        message: MessageToCreate,
        *,
        keyboard: InlineKeyboard | None = None,
    ) -> dict[str, object]:
        self.messages.append(("c2c", target, message))
        self.keyboards.append(keyboard)
        return {"id": f"message-{len(self.messages)}"}

@dataclass(slots=True)
class _FakeMedia:
    result: str = "file-info"
    error: Exception | None = None
    uploads: list[tuple[str, str, QQOfficialImagePayload]] = field(
        default_factory=list
    )

    async def upload_image(
        self,
        scope: str,
        target: str,
        payload: QQOfficialImagePayload,
    ) -> str:
        self.uploads.append((scope, target, payload))
        if self.error is not None:
            raise self.error
        return self.result


def _client(api: _FakeApi, media: _FakeMedia | None = None) -> TencentQQClient:
    return TencentQQClient(
        cast("QQApiClient", api),
        cast("QQOfficialMediaUpload", media or _FakeMedia()),
    )


def _prompt() -> PromptSession:
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-openid",
        account_id="app-id",
    )
    return PromptSession(
        id="session-id",
        actor=ActorRef(
            Platform.QQ_OFFICIAL,
            "member-openid",
            "member",
            conversation.id,
            account_id="app-id",
        ),
        conversation=conversation,
        request_message_id="incoming-id",
        choices=(
            PromptChoice("1", "确认", frozenset({"1", "是", "y"})),
            PromptChoice("0", "取消", frozenset({"0", "否", "n"})),
        ),
        expires_at=100.0,
    )


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
    assert api.keyboards == [None]


@pytest.mark.asyncio
async def test_sdk_client_sends_opt_in_command_keyboard() -> None:
    api = _FakeApi()
    prompt = _prompt()
    rendered = render_qq_official_outbound_message(
        OutboundMessage.from_text("choose"),
        conversation=prompt.conversation,
    )
    assert rendered == (QQOfficialTextPayload("choose"),)
    rendered = render_qq_official_outbound_message(
        OutboundMessage(OutboundMessage.from_text("choose").parts, prompt=prompt),
        conversation=prompt.conversation,
        supports_interactive_prompts=True,
    )

    await TencentQQClient(
        cast("QQApiClient", api),
        cast("QQOfficialMediaUpload", _FakeMedia()),
        custom_keyboards=True,
    ).send_to_group(
        "group-openid",
        rendered,
        msg_id="incoming-id",
        msg_seq=PASSIVE_SEQUENCE,
    )

    keyboard = api.keyboards[0]
    assert keyboard is not None
    body = keyboard.to_dict()
    first = body["content"]["rows"][0]["buttons"][0]
    assert first["render_data"]["label"] == "确认"
    assert first["action"] == {
        "type": 2,
        "permission": {
            "type": 0,
            "specify_user_ids": ["member-openid"],
        },
        "data": "ironsbot:prompt:session-id:1",
        "reply": True,
        "enter": True,
        "unsupport_tips": "请发送对应序号",
    }


@pytest.mark.asyncio
async def test_sdk_client_uploads_binary_image_before_sending_media() -> None:
    api = _FakeApi()
    media = _FakeMedia(result="c2c-file")

    await _client(api, media).send_to_c2c(
        "user-openid",
        (QQOfficialImagePayload(content=b"image", filename="preview.png"),),
    )

    message = api.messages[0][2]
    assert media.uploads == [
        (
            "c2c",
            "user-openid",
            QQOfficialImagePayload(content=b"image", filename="preview.png"),
        )
    ]
    assert message.msg_type == QQMessageType.RICH_MEDIA
    assert message.media is not None
    assert message.media.file_info == "c2c-file"


@pytest.mark.asyncio
async def test_sdk_client_sends_multiple_payloads_with_consecutive_sequences() -> None:
    api = _FakeApi()
    media = _FakeMedia()

    await _client(api, media).send_to_group(
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
    assert media.uploads[0][2].url == "https://example.invalid/image.png"


@pytest.mark.asyncio
async def test_sdk_client_marks_failure_after_first_payload_as_partial() -> None:
    class FailingApi(_FakeApi):
        async def post_group_message(
            self,
            target: str,
            message: MessageToCreate,
            *,
            keyboard: InlineKeyboard | None = None,
        ) -> dict[str, object]:
            if self.messages:
                raise QQOfficialApiError(
                    http_status=400,
                    api_code="11255",
                    message="target unavailable",
                    trace_id="trace-partial",
                )
            return await super().post_group_message(
                target,
                message,
                keyboard=keyboard,
            )

    api = FailingApi()

    with pytest.raises(QQOfficialPartialDeliveryError) as raised:
        await _client(api).send_to_group(
            "group-openid",
            (
                QQOfficialTextPayload("first"),
                QQOfficialTextPayload("second"),
            ),
            msg_id="incoming-id",
            msg_seq=1,
        )

    assert raised.value.message_id == "message-1"
    assert isinstance(raised.value.__cause__, QQOfficialApiError)


@pytest.mark.asyncio
async def test_sdk_client_logs_sequence_without_delivery_identifiers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    api = _FakeApi()
    caplog.set_level("INFO", logger="ironsbot.integrations.qq_official.sdk_client")

    await _client(api).send_to_c2c(
        "private-openid",
        (QQOfficialTextPayload("first"), QQOfficialTextPayload("second")),
        msg_id="incoming-message-id",
        msg_seq=2,
    )

    assert (
        "scope=c2c mode=passive sequence=2 payload=QQOfficialTextPayload"
        in caplog.text
    )
    assert (
        "scope=c2c mode=passive sequence=3 payload=QQOfficialTextPayload"
        in caplog.text
    )
    assert "private-openid" not in caplog.text
    assert "incoming-message-id" not in caplog.text


@pytest.mark.asyncio
async def test_sdk_client_degrades_oversized_image_to_text() -> None:
    api = _FakeApi()
    media = _FakeMedia(
        error=UploadFileTooLargeError(
            "preview.png",
            20,
            limit_bytes=10,
        )
    )

    receipt = await _client(api, media).send_to_group(
        "group-openid",
        (QQOfficialImagePayload(content=b"image", filename="preview.png"),),
        msg_id="incoming-id",
        msg_seq=PASSIVE_SEQUENCE,
    )

    message = api.messages[0][2]
    assert receipt.id == "message-1"
    assert message.msg_type == QQMessageType.TEXT
    assert message.content == "图片超过 QQ 官方平台大小限制，暂时无法发送。"
    assert message.msg_id == "incoming-id"
    assert message.msg_seq == PASSIVE_SEQUENCE


@pytest.mark.asyncio
async def test_sdk_client_degrades_exhausted_daily_upload_quota_to_text() -> None:
    api = _FakeApi()
    media = _FakeMedia(
        error=UploadDailyLimitExceededError("preview.png", 20),
    )

    await _client(api, media).send_to_c2c(
        "user-openid",
        (QQOfficialImagePayload(content=b"image", filename="preview.png"),),
        msg_id="incoming-id",
        msg_seq=PASSIVE_SEQUENCE,
    )

    message = api.messages[0][2]
    assert message.msg_type == QQMessageType.TEXT
    assert message.content == "机器人今日图片上传额度已用完，请稍后再试。"
