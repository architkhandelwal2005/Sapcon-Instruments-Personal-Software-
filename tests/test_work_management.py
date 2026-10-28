"""Assumed due dates, amounts people type, and asking for updates on WhatsApp."""

from datetime import date
from decimal import Decimal

import pytest

from app.extraction.resolve_dates import assumed_due_date
from app.history import _plain
from app.web.routes.leads import _amount
from app.whatsapp.digest import wants_updates


class TestAssumedDueDate:
    def test_three_working_days_on(self):
        assert assumed_due_date(date(2026, 11, 2)) == date(2026, 11, 5)   # Mon -> Thu

    def test_sunday_is_skipped(self):
        assert assumed_due_date(date(2026, 11, 6)) == date(2026, 11, 10)  # Fri -> Tue

    def test_saturday_counts(self):
        assert assumed_due_date(date(2026, 11, 5)) == date(2026, 11, 9)   # Thu -> Mon


class TestAmounts:
    @pytest.mark.parametrize("typed, rupees", [
        ("150000", "150000"), ("1,50,000", "150000"), ("Rs 150000", "150000"),
        ("₹1.5 lakh", "150000"), ("1.5L", "150000"), ("2 cr", "20000000"), ("75k", "75000"),
    ])
    def test_what_people_type(self, typed, rupees):
        amount, readable = _amount(typed)
        assert readable and _plain(amount) == rupees

    def test_empty_clears(self):
        assert _amount("  ") == (None, True)

    def test_nonsense_leaves_the_old_value(self):
        assert _amount("about fifty")[1] is False

    def test_stored_and_typed_amounts_compare_equal(self):
        """Otherwise every Save would log a change from 150000.00 to 150000."""
        assert _plain(Decimal("150000.00")) == _plain(_amount("150000")[0])


class TestAskingForUpdates:
    @pytest.mark.parametrize("text", ["updates", "Updates?", "any updates", "What's new", "kya update hai"])
    def test_these_ask(self, text):
        assert wants_updates(text)

    @pytest.mark.parametrize("text", ["update Vishal's task to done", "met Rajesh today, good update on Parag"])
    def test_a_sentence_with_the_word_is_not_a_request(self, text):
        assert not wants_updates(text)
