"""The rate limiter on its own, with a fake clock instead of a real wait."""

from insurance_mcp.rate_limit import RateLimiter


def test_a_blocked_key_gets_its_full_limit_back_once_its_hits_leave_the_window():
    now = 1000.0
    limiter = RateLimiter(limit=2, window_seconds=60, clock=lambda: now)

    assert limiter.hit("1.2.3.4") is None
    assert limiter.hit("1.2.3.4") is None
    assert limiter.hit("1.2.3.4") == 60  # blocked: wait 60 seconds

    now += 59.5
    assert limiter.hit("1.2.3.4") == 1  # still blocked: wait 1 more second

    # A minute after the first two hits, both are allowed again. If the rejected
    # hits above had been counted, the second of these would be blocked.
    now += 0.5
    assert limiter.hit("1.2.3.4") is None
    assert limiter.hit("1.2.3.4") is None
