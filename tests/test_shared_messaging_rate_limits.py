from ironsbot.shared.messaging.rate_limits import InMemoryRateLimiter


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
