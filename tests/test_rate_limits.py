"""Two rate limits wear the same 429 and mean opposite things.

The per-minute one clears in under a minute; one voice note can trip it by
itself, because a note naming eight people used to spend a model call on each.
The per-day one keeps refusing until it resets. Telling him the day's limit is
gone when it is the minute's sends him away for hours over nothing.
"""

import pytest

from app.llm import _retry_after, is_daily_limit

PER_MINUTE = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota', 'details': [{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel', "
    "'quotaMetric': 'generate_content_requests_per_minute'}, {'retryDelay': '12s'}]}}"
)

PER_DAY = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your "
    "current quota', 'details': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel', "
    "'quotaMetric': 'generate_content_free_tier_requests per day'}, {'retryDelay': '30s'}]}}"
)


def test_the_daily_limit_is_recognised():
    assert is_daily_limit(Exception(PER_DAY)) is True


def test_the_per_minute_limit_is_not_the_daily_one():
    assert is_daily_limit(Exception(PER_MINUTE)) is False


def test_a_per_minute_limit_is_waited_out():
    wait = _retry_after(Exception(PER_MINUTE))
    assert wait is not None and 12 <= wait <= 70


def test_a_daily_limit_is_never_waited_out():
    """It asks for thirty seconds and then refuses for hours. Sitting on that
    inside a webhook achieves nothing."""
    assert _retry_after(Exception(PER_DAY)) is None


def test_an_error_that_is_not_a_rate_limit_is_not_waited_out():
    assert _retry_after(Exception("503 UNAVAILABLE")) is None
    assert _retry_after(Exception("400 INVALID_ARGUMENT")) is None


@pytest.mark.parametrize("text", [PER_MINUTE, PER_DAY])
def test_neither_is_mistaken_for_a_transient_capacity_error(text):
    from app.llm import _is_transient

    assert _is_transient(Exception(text)) is False
