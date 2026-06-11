from pytest import MonkeyPatch

from ironsbot.shared.messaging import query_guard
from ironsbot.shared.messaging.query_guard import QueryGuard
from ironsbot.shared.messaging.rate_limits import rate_limiter

SUBJECT_ID = 100


def _guard() -> QueryGuard:
    return QueryGuard(
        success_namespace="query_guard_test.success",
        failure_namespace="query_guard_test.failure",
        success_cooldown=lambda: 10,
        failure_cooldown=lambda: 20,
    )


def test_query_guard_tracks_in_progress_subjects(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(query_guard, "is_superuser", lambda _user_id: False)
    guard = _guard()

    guard.set_in_progress(1, SUBJECT_ID)

    assert guard.in_progress_subject(1) == SUBJECT_ID

    guard.clear_in_progress(1)

    assert guard.in_progress_subject(1) is None


def test_query_guard_ignores_superuser_in_progress(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(query_guard, "is_superuser", lambda _user_id: True)
    guard = _guard()

    guard.set_in_progress(1, SUBJECT_ID)

    assert guard.in_progress_subject(1) is None


def test_query_guard_uses_success_and_failure_cooldowns(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(query_guard, "is_superuser", lambda _user_id: False)
    rate_limiter.clear("query_guard_test.success")
    rate_limiter.clear("query_guard_test.failure")
    guard = _guard()

    assert guard.remaining_seconds(1) == 0

    guard.penalize_success(1)
    guard.penalize_failure(1)

    assert guard.remaining_seconds(1) in range(1, 21)

    rate_limiter.clear("query_guard_test.success")
    rate_limiter.clear("query_guard_test.failure")
