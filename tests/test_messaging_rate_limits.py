from ironsbot.services.messaging.rate_limits import SlidingWindowRateLimiter


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
