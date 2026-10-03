"""Putting the rows back in an order the database will accept.

Export is easy; restore is where a backup turns out to be worthless. Every way
it can fail here is a foreign key, and the whole decision is one pure function
that can be checked without a database.
"""

import pytest

from scripts.backup import _plain, _plan

# The shapes this schema actually has: leads point at entities, tasks at
# meetings, entities at themselves - and entities and capture_events point at
# each other, because an entity records the photographed card it came from and
# a card records the person who logged it.
KEYS = [
    ("leads", "entity_id", "entities"),
    ("leads", "assigned_to", "entities"),
    ("meetings", "primary_contact_id", "entities"),
    ("tasks", "meeting_id", "meetings"),
    ("entities", "possible_duplicate_of", "entities"),
    ("entities", "merged_into", "entities"),
    ("entities", "capture_event_id", "capture_events"),
    ("capture_events", "logged_by", "entities"),
]
TABLES = ["tasks", "leads", "entities", "meetings", "capture_events", "schema_migrations"]
# Every one of those foreign keys is allowed to be empty, as they are in the
# real schema.
NULLABLE = {(t, c) for t, c, _target in KEYS}


def _order(tables=None, keys=None, nullable=None):
    return _plan(tables or TABLES, keys or KEYS,
                 NULLABLE if nullable is None else nullable)[0]


def _held(tables=None, keys=None, nullable=None):
    return _plan(tables or TABLES, keys or KEYS,
                 NULLABLE if nullable is None else nullable)[1]


def test_a_table_comes_after_everything_it_points_at():
    order = _order()
    assert order.index("entities") < order.index("leads")
    assert order.index("entities") < order.index("meetings")
    assert order.index("meetings") < order.index("tasks")


def test_two_tables_pointing_at_each_other_still_get_an_order():
    """The bug this was written for: a cycle made the sort give up and emit
    every remaining table alphabetically, which put app_sessions, app_users and
    capture_events ahead of the entities they all reference."""
    order = _order()
    assert order.index("entities") < order.index("leads")
    assert order.index("entities") < order.index("tasks")


def test_the_cycle_is_broken_by_deferring_a_column_that_may_be_empty():
    held = _held()
    broken = held.get("entities", set()) | held.get("capture_events", set())
    assert {"capture_event_id"} & broken or {"logged_by"} & broken


def test_a_column_that_cannot_be_empty_is_never_deferred():
    """Filling a required column with a null to make the ordering work would
    be a repair that breaks the thing it is repairing."""
    order, held = _plan(TABLES, KEYS, nullable=set())
    assert all("capture_event_id" not in cols for cols in held.values())
    assert sorted(order) == sorted(TABLES)


def test_a_self_reference_is_always_deferred():
    """No order satisfies one - some row has to go in first."""
    assert _held()["entities"] >= {"possible_duplicate_of", "merged_into"}


def test_a_table_without_self_references_defers_nothing():
    assert "leads" not in _held()


def test_a_table_nothing_depends_on_is_still_included():
    assert "schema_migrations" in _order()


def test_every_table_appears_exactly_once():
    assert sorted(_order()) == sorted(TABLES)


def test_the_order_does_not_depend_on_the_order_given():
    assert _order(TABLES) == _order(list(reversed(TABLES)))


def test_a_key_pointing_outside_the_backup_is_ignored():
    assert _order(["leads"]) == ["leads"]


def test_a_cycle_with_nothing_nullable_still_produces_an_order():
    """Nothing in this schema hits it. Stalling forever would be worse than an
    order the database rejects out loud."""
    cyclic = [("a", "b_id", "b"), ("b", "a_id", "a")]
    assert sorted(_plan(["a", "b"], cyclic, set())[0]) == ["a", "b"]


def test_a_three_table_cycle_is_broken_too():
    cyclic = [("a", "b_id", "b"), ("b", "c_id", "c"), ("c", "a_id", "a")]
    nullable = {(t, c) for t, c, _ in cyclic}
    order, held = _plan(["a", "b", "c"], cyclic, nullable)
    assert sorted(order) == ["a", "b", "c"]
    assert sum(len(v) for v in held.values()) == 1    # one edge cut, not all three


@pytest.mark.parametrize("value", [None, True, 42, 1.5, "text", {"a": 1}, [1, 2]])
def test_json_native_values_pass_through_untouched(value):
    assert _plain(value) == value


def test_a_date_becomes_text_postgres_can_read_back():
    from datetime import date, datetime

    assert _plain(date(2026, 10, 3)) == "2026-10-03"
    assert _plain(datetime(2026, 10, 3, 9, 30)).startswith("2026-10-03T09:30")


def test_anything_else_becomes_text_rather_than_breaking_the_dump():
    """A uuid or a Decimal cannot go into JSON. Losing the whole backup over
    one column is the failure that matters here."""
    import uuid
    from decimal import Decimal

    u = uuid.uuid4()
    assert _plain(u) == str(u)
    assert _plain(Decimal("1.50")) == "1.50"
