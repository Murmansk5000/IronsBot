from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from nonebot.adapters.onebot.v11 import Message

from ironsbot.integrations.onebot.message_envelope import decode_received_message
from ironsbot.integrations.onebot.message_input import message_input_context
from ironsbot.integrations.onebot.message_segments import (
    OneBotMessageDecodeError,
    decode_onebot_segments,
    encode_onebot_message,
    onebot_message_text,
)
from tests.helpers.onebot_events import group_message_event

if TYPE_CHECKING:
    from pytest import LogCaptureFixture

    from ironsbot.integrations.onebot.message_segments import OneBotMessage


@pytest.mark.parametrize(
    "source",
    [
        "",
        "普通文本",
        "left&#91;x&#93;&amp;right",
        "text&#44;text",
        "[CQ:at,qq=42] 帮助",
        "[CQ:at,qq=all]",
        "[CQ:reply,id=-12]米米号",
        "[CQ:shake][CQ:face,id=1][CQ:image,file=a.png]",
        "[CQ:share,title=a=b&#44;c,url=https://example.test/?a=1&amp;b=2]",
        "&#91;CQ:at,qq=42&#93;",
        "&amp;#91;CQ:at,qq=42&amp;#93;",
        "[CQ:at,qq=42,]",
        "[CQ:at,qq=42,qq=43]",
        "[CQ:at, qq=42]",
        "[CQ:at,qq]",
        "[CQ:at,qq=42",
        "[CQ:text,text=literal]suffix",
        "[CQ:text]suffix",
        "prefix[CQ:custom.type-1,key=a\nb]suffix",
        "[CQ:未知,key=x]",
    ],
)
def test_cq_decoding_matches_existing_transport_semantics(source: str) -> None:
    native = Message(source)
    expected: OneBotMessage = [
        {"type": part.type, "data": part.data} for part in native
    ]
    assert decode_onebot_segments(source) == expected
    assert encode_onebot_message(expected) == str(native)
    assert (
        onebot_message_text(decode_onebot_segments(source))
        == native.extract_plain_text()
    )


def test_array_text_is_literal_and_data_is_not_unescaped_or_reparsed() -> None:
    source = [{"type": "text", "data": {"text": "[CQ:at,qq=42] &#91;x&#93;"}}]
    decoded = decode_onebot_segments(source)
    assert decoded == source
    assert decoded is not source and decoded[0]["data"] is not source[0]["data"]
    decoded[0]["data"]["text"] = "changed"
    assert source[0]["data"]["text"] == "[CQ:at,qq=42] &#91;x&#93;"


def test_array_can_preserve_nested_custom_data_and_null_parameter_objects() -> None:
    assert decode_onebot_segments(
        [
            {"type": "shake", "data": None},
            {"type": "custom", "data": {"items": [1, {"text": "x"}]}},
        ]
    ) == [
        {"type": "shake", "data": {}},
        {"type": "custom", "data": {"items": [1, {"text": "x"}]}},
    ]


@pytest.mark.parametrize(
    "source",
    [
        None,
        1,
        {},
        ["text"],
        [{"type": None}],
        [{"type": ""}],
        [{"type": "at", "data": []}],
        [{"type": "text", "data": None}],
        [{"type": "text", "data": {"text": 123}}],
    ],
)
def test_invalid_segment_shapes_have_no_payload_in_errors(source: object) -> None:
    with pytest.raises(
        OneBotMessageDecodeError, match=r"^Invalid OneBot message segments$"
    ):
        decode_onebot_segments(source)


@pytest.mark.parametrize("sent", [False, True])
def test_received_and_sent_messages_pass_cq_through_the_canonical_codec(
    *, sent: bool
) -> None:
    payload = group_message_event("hello", user_id=1 if sent else 101).model_dump()
    payload.pop("original_message", None)
    payload["message"] = "[CQ:at,qq=42]执行"
    if sent:
        payload["post_type"] = "message_sent"
    event = decode_received_message(payload)
    assert event is not None
    assert event.message[0]["type"] == "at"
    assert event.message[0]["data"]["qq"] == "42"
    assert payload["message"] == "[CQ:at,qq=42]执行"


def test_bad_message_is_rejected_before_native_payload_logging(
    caplog: LogCaptureFixture,
) -> None:
    payload = group_message_event().model_dump()
    payload["message"] = [
        {"type": "text", "data": {"text": {"secret": "private-marker"}}}
    ]
    assert decode_received_message(payload) is None
    assert "private-marker" not in caplog.text
    assert "invalid message segments" in caplog.text


@pytest.mark.parametrize("post_type", [None, [], {"secret": "private-marker"}])
def test_invalid_event_kind_is_rejected_without_logging_source(
    caplog: LogCaptureFixture,
    post_type: object,
) -> None:
    payload = group_message_event().model_dump()
    payload["post_type"] = post_type
    assert decode_received_message(payload) is None
    assert "private-marker" not in caplog.text


def test_snapshot_text_does_not_call_native_plaintext_or_use_exception_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(_self: object) -> str:
        pytest.fail("snapshot text must come from its canonical segments")

    event = group_message_event("执行")
    monkeypatch.setattr(type(event), "get_plaintext", forbidden)
    assert message_input_context(event).text == "执行"


def test_cq_and_arrays_decode_in_process_without_nonebot() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.modules['nonebot'] = None
from ironsbot.integrations.onebot.message_segments import (
    decode_onebot_segments, onebot_message_text,
)
segments = decode_onebot_segments('[CQ:at,qq=42]help')
assert segments[0]['type'] == 'at'
assert onebot_message_text(segments) == 'help'
literal = [{'type': 'text', 'data': {'text': '[CQ:at,qq=42]'}}]
assert decode_onebot_segments(literal) == literal
""",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
