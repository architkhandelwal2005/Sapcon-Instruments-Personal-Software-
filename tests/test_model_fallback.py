"""When the small model is out of free capacity, use a bigger one.

Free-tier requests are served from spare capacity and the small models run out
of it first: on one evening every -lite model answered 503 while
gemini-3.5-flash answered normally. Retrying the same refused model harder does
not help.
"""

import pytest

import app.llm as llm


class ServerError(Exception):
    """Same class name google-genai raises for a 5xx."""


BUSY = "503 UNAVAILABLE. This model is currently experiencing high demand."


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda _s: None)


def _two_models(monkeypatch):
    monkeypatch.setattr(llm, "_GEMINI_MODEL", "small")
    monkeypatch.setattr(llm, "_GEMINI_FALLBACK", "big")


def test_the_configured_model_is_used_when_it_answers(monkeypatch):
    _two_models(monkeypatch)
    used = []
    assert llm.try_models(lambda m: used.append(m) or "answer") == "answer"
    assert used == ["small"]


def test_a_refused_model_gives_way_to_the_bigger_one(monkeypatch):
    _two_models(monkeypatch)
    used = []

    def call(model):
        used.append(model)
        if model == "small":
            raise ServerError(BUSY)
        return "answer"

    assert llm.try_models(call) == "answer"
    assert used[0] == "small" and used[-1] == "big"


def test_the_first_model_is_retried_before_the_second_is_tried(monkeypatch):
    """A brief spike should be ridden out on the model we wanted, not escalated
    at the first refusal - the bigger model is slower and costs more."""
    _two_models(monkeypatch)
    used = []

    def call(model):
        used.append(model)
        if len(used) < 3:
            raise ServerError(BUSY)
        return "answer"

    assert llm.try_models(call) == "answer"
    assert used == ["small", "small", "small"]      # never reached the fallback


def test_a_permanent_error_is_not_doubled(monkeypatch):
    """A bad request fails the same way on both models, and a wasted call is a
    call gone from a daily allowance."""
    _two_models(monkeypatch)
    used = []

    def call(model):
        used.append(model)
        raise ValueError("400 INVALID_ARGUMENT")

    with pytest.raises(ValueError):
        llm.try_models(call)
    assert used == ["small"]


def test_both_refusing_raises_the_last_failure(monkeypatch):
    _two_models(monkeypatch)

    def call(model):
        raise ServerError(BUSY)

    with pytest.raises(ServerError):
        llm.try_models(call)


def test_no_fallback_configured_means_one_model(monkeypatch):
    monkeypatch.setattr(llm, "_GEMINI_MODEL", "small")
    monkeypatch.setattr(llm, "_GEMINI_FALLBACK", "")
    assert llm.gemini_models() == ["small"]


def test_a_fallback_the_same_as_the_model_is_not_a_fallback(monkeypatch):
    monkeypatch.setattr(llm, "_GEMINI_MODEL", "same")
    monkeypatch.setattr(llm, "_GEMINI_FALLBACK", "same")
    assert llm.gemini_models() == ["same"]
