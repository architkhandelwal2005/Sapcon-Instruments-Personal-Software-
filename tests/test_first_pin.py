"""Claiming an account - the one place where a login is created without anyone
already holding one. The invariant that matters: it can never take over an
account that already has a PIN."""

import pytest

from app.web.auth import claim_account, hash_pin


class _Cursor:
    """Just enough psycopg to answer the one SELECT and record the one UPDATE."""

    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        if sql.strip().lower().startswith("select"):
            self._row = self.store["row"]
        else:
            self.store["updates"].append((sql, params))
            self._row = None

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row):
        self.store = {"row": row, "updates": []}
        self.committed = False

    def cursor(self):
        return _Cursor(self.store)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


def _row(pin_hash=None, disabled=False):
    return ("e1", "Vishal Dixit", "employee", pin_hash, disabled)


def test_a_registered_number_with_no_pin_sets_one_and_is_signed_in():
    conn = _Conn(_row())
    actor, reason = claim_account(conn, "9893351932", "654321")
    assert reason == ""
    assert actor.name == "Vishal Dixit" and actor.role == "employee"
    assert conn.committed and len(conn.store["updates"]) == 1


def test_an_account_that_already_has_a_pin_cannot_be_claimed_again():
    conn = _Conn(_row(pin_hash=hash_pin("111111")))
    actor, reason = claim_account(conn, "9893351932", "654321")
    assert actor is None and reason == "already_set"
    assert conn.store["updates"] == []          # nothing was written


def test_a_turned_off_account_cannot_be_claimed():
    conn = _Conn(_row(disabled=True))
    actor, reason = claim_account(conn, "9893351932", "654321")
    assert actor is None and reason == "disabled"
    assert conn.store["updates"] == []


def test_a_number_nobody_registered_is_told_so_and_writes_nothing():
    """Registration is open to anyone who reaches the page, so this is the
    common case, not an attack: the office has not added them yet. Saying so is
    the only thing they cannot work out for themselves."""
    conn = _Conn(None)
    actor, reason = claim_account(conn, "9893351932", "654321")
    assert actor is None and reason == "not_registered"
    assert conn.store["updates"] == []


@pytest.mark.parametrize("weak", ["12345", "", "abcdef", "1234a6"])
def test_a_pin_that_is_too_short_or_not_digits_never_reaches_the_database(weak):
    conn = _Conn(_row())
    actor, reason = claim_account(conn, "9893351932", weak)
    assert actor is None and reason == "weak_pin"
    assert conn.store["updates"] == []


def test_a_phone_number_that_cannot_be_real_is_refused_before_any_lookup():
    conn = _Conn(_row())
    actor, reason = claim_account(conn, "not a number", "654321")
    assert actor is None and reason == "bad"
    assert conn.store["updates"] == []
