from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ironsbot"
    / "custom_plugins"
    / "ai_mention_guard"
    / "service.py"
)
_SPEC = spec_from_file_location("ai_mention_guard_service_for_test", _SERVICE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SERVICE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SERVICE)
GuardReplyLimiter = _SERVICE.GuardReplyLimiter


def test_guard_reply_limiter_caps_messages_per_window() -> None:
    now = 100.0
    limiter = GuardReplyLimiter(
        window_seconds=60.0,
        max_per_window=2,
        clock=lambda: now,
    )

    assert limiter.can_send(123)
    assert limiter.can_send(123)
    assert not limiter.can_send(123)


def test_guard_reply_limiter_expires_old_messages() -> None:
    current_time = 100.0

    def clock() -> float:
        return current_time

    limiter = GuardReplyLimiter(
        window_seconds=60.0,
        max_per_window=1,
        clock=clock,
    )

    assert limiter.can_send(123)
    assert not limiter.can_send(123)

    current_time = 160.0
    assert limiter.can_send(123)
