from pytest import MonkeyPatch

from ironsbot.shared.messaging import query_guard
from ironsbot.shared.messaging.query_guard import QueryGuard
from ironsbot.shared.messaging.rate_limits import rate_limiter

SUBJECT_ID = 100


def _guard() -> QueryGuard:
    return QueryGuard(
        namespace="query_guard_test",
        cooldown=lambda: 20,
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


def test_query_guard_finishes_with_one_cooldown(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(query_guard, "is_superuser", lambda _user_id: False)
    rate_limiter.clear("query_guard_test")
    guard = _guard()
    guard.set_in_progress(1, SUBJECT_ID)

    assert guard.remaining_seconds(1) == 0

    guard.finish(1)

    assert guard.remaining_seconds(1) in range(1, 21)
    assert guard.in_progress_subject(1) is None

    rate_limiter.clear("query_guard_test")


def test_query_guard_keeps_command_cooldowns_independent(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(query_guard, "is_superuser", lambda _user_id: False)
    rate_limiter.clear("query_guard_test.player")
    rate_limiter.clear("query_guard_test.team")
    player_guard = QueryGuard(
        namespace="query_guard_test.player",
        cooldown=lambda: 20,
    )
    team_guard = QueryGuard(
        namespace="query_guard_test.team",
        cooldown=lambda: 20,
    )

    player_guard.finish(1)

    assert player_guard.remaining_seconds(1) in range(1, 21)
    assert team_guard.remaining_seconds(1) == 0

    rate_limiter.clear("query_guard_test.player")
    rate_limiter.clear("query_guard_test.team")


def test_query_guard_superuser_has_no_cooldown(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(query_guard, "is_superuser", lambda _user_id: True)
    rate_limiter.clear("query_guard_test")
    guard = _guard()

    guard.finish(1)

    assert guard.remaining_seconds(1) == 0

    rate_limiter.clear("query_guard_test")
