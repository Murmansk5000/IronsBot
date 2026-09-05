import pytest

from ironsbot.core.tasks import OperationDeadline


def test_deadline_caps_stages_without_resetting_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr("ironsbot.core.tasks.monotonic", lambda: now[0])
    total, cap, spent = 10, 3, 8
    deadline = OperationDeadline.after(total)
    assert deadline.remaining(cap) == cap
    now[0] += 8
    assert deadline.remaining(cap) == total - spent
    assert deadline.remaining() == total - spent
    now[0] += 5
    assert deadline.remaining() == 0
    assert deadline.remaining(cap) == 0


def test_expired_or_negative_budget_never_allows_work() -> None:
    assert OperationDeadline.after(-1).remaining() == 0
    assert OperationDeadline.after(10).remaining(-1) == 0
