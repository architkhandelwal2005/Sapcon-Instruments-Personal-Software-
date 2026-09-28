"""A model that says it is busy must be called again, not given up on.

Two real messages were lost to a 503 that was raised on the first attempt:
the retry seam knew about dropped connections and rate limits, and a capacity
error is neither."""

import pytest

from app.llm import _is_transient, with_retries


class ServerError(Exception):
    """Same class name google-genai raises for a 5xx."""


class ValidationError(Exception):
    pass


BUSY = "503 UNAVAILABLE. {'error': {'code': 503, 'message': 'This model is currently experiencing high demand.'}}"


@pytest.mark.parametrize("exc", [
    ServerError(BUSY),
    Exception("503 UNAVAILABLE"),
    Exception("The model is overloaded. Please try again later."),
    Exception("500 INTERNAL"),
])
def test_a_provider_saying_it_is_busy_is_transient(exc):
    assert _is_transient(exc) is True


@pytest.mark.parametrize("exc", [
    ValidationError("field required"),
    Exception("400 INVALID_ARGUMENT"),
    Exception("401 permission denied"),
])
def test_a_real_error_is_not_retried_into_the_ground(exc):
    assert _is_transient(exc) is False


def test_a_busy_model_is_called_again_and_the_answer_is_returned(monkeypatch):
    monkeypatch.setattr("app.llm.time.sleep", lambda _s: None)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ServerError(BUSY)
        return "transcript"

    assert with_retries(flaky) == "transcript"
    assert len(calls) == 3


def test_a_permanent_error_is_raised_at_once(monkeypatch):
    monkeypatch.setattr("app.llm.time.sleep", lambda _s: None)
    calls = []

    def broken():
        calls.append(1)
        raise ValidationError("field required")

    with pytest.raises(ValidationError):
        with_retries(broken)
    assert len(calls) == 1          # not retried
