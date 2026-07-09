from pytest import MonkeyPatch

from ironsbot.services.bilibili import permissions
from tests.helpers.onebot_events import private_message_event


def test_bili_superusers_are_sorted(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(permissions, "get_superuser_ids", lambda: {3, 1, 2})

    assert permissions.get_bili_superuser_uids() == [1, 2, 3]
    assert permissions.is_bili_superuser(2)
    assert not permissions.is_bili_superuser(4)


def test_dynamic_update_requires_bili_superuser(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(permissions, "get_superuser_ids", lambda: {42})

    assert permissions.is_dynamic_update_allowed(private_message_event(user_id=42))
    assert not permissions.is_dynamic_update_allowed(private_message_event(user_id=7))


def test_dynamic_query_uses_feature_service(
    monkeypatch: MonkeyPatch,
) -> None:
    seen: list[tuple[object, str]] = []

    def fake_is_event_feature_allowed(event: object, feature: str) -> bool:
        seen.append((event, feature))
        return True

    monkeypatch.setattr(
        permissions,
        "is_event_feature_allowed",
        fake_is_event_feature_allowed,
    )
    event = private_message_event(user_id=42)

    assert permissions.is_dynamic_query_allowed(event)
    assert seen == [(event, "bili_query")]
