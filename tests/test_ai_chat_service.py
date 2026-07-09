import nonebot
import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from pytest import MonkeyPatch

GROUP_ID = 456
USER_ID = 123


try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

service = pytest.importorskip("ironsbot.services.ai.chat")
constants = pytest.importorskip("ironsbot.services.ai.constants")
ai_client = pytest.importorskip("ironsbot.services.ai.client")
source_context = pytest.importorskip("ironsbot.services.ai.source_context")


def _group_event() -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=USER_ID,
        message_type="group",
        message_id=3,
        message=Message("hello"),
        original_message=Message("hello"),
        raw_message="hello",
        font=0,
        group_id=GROUP_ID,
        sender={},
    )


def test_can_show_admin_notice_for_superuser(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(service, "is_superuser", lambda user_id: user_id == USER_ID)
    monkeypatch.setattr(service, "group_has_feature", lambda *_args: False)

    assert service.can_show_admin_notice(_group_event())


def test_can_show_admin_notice_for_admin_notice_group(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "is_superuser", lambda _user_id: False)
    monkeypatch.setattr(
        service,
        "group_has_feature",
        lambda group_id, feature: group_id == GROUP_ID and feature == "admin_notice",
    )

    assert service.can_show_admin_notice(_group_event())


def test_can_hide_admin_notice_for_regular_group(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "is_superuser", lambda _user_id: False)
    monkeypatch.setattr(service, "group_has_feature", lambda *_args: False)

    assert not service.can_show_admin_notice(_group_event())


def test_ai_error_reply_detection() -> None:
    assert service.is_ai_error_reply(constants.REQUEST_FAILED_REPLY)
    assert service.is_ai_error_reply(constants.EMPTY_REPLY)
    assert not service.is_ai_error_reply("正常回复")


def test_ai_notice_source_context_includes_group_user_and_message() -> None:
    event = GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=USER_ID,
        message_type="group",
        message_id=33,
        message=Message("hello"),
        original_message=Message("hello"),
        raw_message="hello",
        font=0,
        group_id=GROUP_ID,
        sender={"card": "群名片"},
    )

    source = source_context.build_ai_notice_source_context(event, "你好")

    assert f"群：{GROUP_ID}" in source
    assert f"用户：{USER_ID}（群名片）" in source
    assert "消息ID：33" in source
    assert "消息：你好" in source


def test_ai_client_notice_appends_source_context() -> None:
    message = source_context.append_ai_notice_source_context(
        "AI聊天接口异常。",
        "群：456",
    )

    assert message == "AI聊天接口异常。\n\n触发来源：\n群：456"
