from dataclasses import dataclass
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, PrivateMessageEvent

_SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ironsbot"
    / "custom_plugins"
    / "meeting_reply"
    / "service.py"
)
_SPEC = spec_from_file_location("meeting_reply_service_for_test", _SERVICE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SERVICE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SERVICE)
build_meeting_reply = _SERVICE.build_meeting_reply
is_meeting_command_event = _SERVICE.is_meeting_command_event


@dataclass
class MeetingConfig:
    number: str
    commands: tuple[str, ...] = ("会议",)
    template: str = (
        "腾讯会议\n"
        "腾讯会议号：{meeting_number}\n"
        "点击链接直接加入：{meeting_url}"
    )


def _group_event(text: str = "会议") -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=2,
        message_type="group",
        message_id=3,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        group_id=4,
        sender={},
    )


def _private_event(text: str = "会议") -> PrivateMessageEvent:
    return PrivateMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="friend",
        user_id=2,
        message_type="private",
        message_id=3,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        sender={},
    )


def test_build_meeting_reply_returns_none_without_number() -> None:
    assert build_meeting_reply(MeetingConfig(number="")) is None


def test_build_meeting_reply_formats_tencent_meeting_number() -> None:
    reply = build_meeting_reply(
        MeetingConfig(
            number="6638682008",
            template=(
                "会议号：{meeting_number}\n"
                "数字：{meeting_digits}\n"
                "链接：{meeting_url}"
            ),
        )
    )

    assert reply == (
        "会议号：663-868-2008\n"
        "数字：6638682008\n"
        "链接：https://meeting.tencent.com/p/6638682008"
    )


def test_is_meeting_command_event_requires_group_feature() -> None:
    matched = is_meeting_command_event(
        _group_event(),
        MeetingConfig(number="6638682008"),
        is_group_allowed=lambda *_args: False,
        is_private_allowed=lambda *_args: True,
        command_matches=lambda text, commands: text in commands,
    )

    assert not matched


def test_is_meeting_command_event_allows_private_command() -> None:
    matched = is_meeting_command_event(
        _private_event(),
        MeetingConfig(number="6638682008"),
        is_group_allowed=lambda *_args: False,
        is_private_allowed=lambda *_args: True,
        command_matches=lambda text, commands: text in commands,
    )

    assert matched
