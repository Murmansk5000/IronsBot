from nonebot.adapters.onebot.v11 import (
    GroupIncreaseNoticeEvent,
    GroupMessageEvent,
    PrivateMessageEvent,
)

from tests.helpers.onebot_events import (
    group_admin_message_event,
    group_increase_notice_event,
    group_member_message_event,
    group_message_event,
    group_owner_message_event,
    private_message_event,
)

USER_ID = 2
GROUP_ID = 4
OPERATOR_ID = 6


def test_group_message_event_builder_sets_group_context() -> None:
    event = group_message_event("hello", user_id=USER_ID, group_id=GROUP_ID)

    assert isinstance(event, GroupMessageEvent)
    assert event.raw_message == "hello"
    assert event.user_id == USER_ID
    assert event.group_id == GROUP_ID


def test_group_member_role_event_builders_set_sender_role() -> None:
    member_event = group_member_message_event(
        user_id=USER_ID,
        group_id=GROUP_ID,
        role="member",
    )
    admin_event = group_admin_message_event(user_id=USER_ID, group_id=GROUP_ID)
    owner_event = group_owner_message_event(user_id=USER_ID, group_id=GROUP_ID)

    assert member_event.sender.role == "member"
    assert admin_event.sender.role == "admin"
    assert owner_event.sender.role == "owner"


def test_private_message_event_builder_sets_private_context() -> None:
    event = private_message_event("hello", user_id=USER_ID)

    assert isinstance(event, PrivateMessageEvent)
    assert event.raw_message == "hello"
    assert event.user_id == USER_ID


def test_group_increase_notice_event_builder_sets_notice_context() -> None:
    event = group_increase_notice_event(
        user_id=USER_ID,
        group_id=GROUP_ID,
        operator_id=OPERATOR_ID,
    )

    assert isinstance(event, GroupIncreaseNoticeEvent)
    assert event.notice_type == "group_increase"
    assert event.user_id == USER_ID
    assert event.group_id == GROUP_ID
    assert event.operator_id == OPERATOR_ID
