from ironsbot.shared.messaging.rate_limits import (
    InMemoryRateLimiter,
    SlidingWindowRateLimiter,
)


def test_in_memory_rate_limiter_reports_remaining_seconds() -> None:
    limiter = InMemoryRateLimiter()

    assert limiter.remaining_seconds("query", 1, 10) == 0

    limiter.penalize("query", 1, 10)

    assert limiter.remaining_seconds("query", 1, 10) in range(1, 11)


def test_in_memory_rate_limiter_respects_exempt_subjects() -> None:
    limiter = InMemoryRateLimiter()

    limiter.penalize("query", 1, 10, exempt=True)

    assert limiter.remaining_seconds("query", 1, 10) == 0


def test_in_memory_rate_limiter_clears_namespace() -> None:
    limiter = InMemoryRateLimiter()
    limiter.penalize("query", 1, 10)
    limiter.penalize("other", 1, 10)

    limiter.clear("query")

    assert limiter.remaining_seconds("query", 1, 10) == 0
    assert limiter.remaining_seconds("other", 1, 10) in range(1, 11)


def test_sliding_window_rate_limiter_reports_remaining_capacity() -> None:
    limiter = SlidingWindowRateLimiter()

    assert limiter.hit("outbound", 1, window_seconds=10, max_events=2, now=0) == 1
    assert limiter.hit("outbound", 1, window_seconds=10, max_events=2, now=1) == 0
    assert limiter.hit("outbound", 1, window_seconds=10, max_events=2, now=2) == -1
    assert limiter.hit("outbound", 1, window_seconds=10, max_events=2, now=11) == 1


def test_sliding_window_rate_limiter_clears_namespace() -> None:
    limiter = SlidingWindowRateLimiter()
    limiter.hit("outbound", 1, window_seconds=10, max_events=2, now=0)
    limiter.hit("other", 1, window_seconds=10, max_events=2, now=0)

    limiter.clear("outbound")

    assert limiter.hit("outbound", 1, window_seconds=10, max_events=2, now=1) == 1
    assert limiter.hit("other", 1, window_seconds=10, max_events=2, now=1) == 0
