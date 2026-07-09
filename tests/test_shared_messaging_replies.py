from ironsbot.shared.messaging.replies import event_sender_at_user_ids
from tests.helpers.onebot_events import group_message_event, private_message_event


def _group_event(
    text: str = "帮助",
    *,
    user_id: int = 2,
    self_id: int = 1,
):
    return group_message_event(
        text,
        user_id=user_id,
        group_id=4,
        self_id=self_id,
    )


def _private_event(text: str = "帮助"):
    return private_message_event(
        text,
        user_id=2,
    )


def test_event_sender_at_user_ids_mentions_group_sender() -> None:
    assert event_sender_at_user_ids(_group_event()) == (2,)


def test_event_sender_at_user_ids_ignores_self_group_message() -> None:
    assert event_sender_at_user_ids(_group_event(user_id=1, self_id=1)) == ()


def test_event_sender_at_user_ids_ignores_private_sender() -> None:
    assert event_sender_at_user_ids(_private_event()) == ()


def test_event_sender_at_user_ids_ignores_missing_event() -> None:
    assert event_sender_at_user_ids(None) == ()
