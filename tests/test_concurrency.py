"""One person's messages are worked on one at a time.

Each WhatsApp message is processed in the background, so two voice notes sent
seconds apart ran side by side. When both mentioned a company nobody had
recorded yet, each looked, found nothing, and created it - two records of one
customer. He sends notes back to back between meetings, so this was the
realistic case, not an edge one.

The lock itself was proved against the real Supabase pooler: a second holder
waits for the first, a different sender is not blocked, and the lock is gone
afterwards. These tests pin the part that cannot be seen from outside - that
the lock is always released, including when the work fails.
"""

import pytest

from app.web.routes import whatsapp


class _Cursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append(("sql", " ".join(sql.split())))


class _Conn:
    def __init__(self, fail_unlock=False):
        self.log = []
        self.closed = False
        self.fail_unlock = fail_unlock

    def cursor(self):
        if self.fail_unlock and any("advisory_lock(" in e[1] for e in self.log if e[0] == "sql"):
            # Once locked, the next statement (the unlock) blows up.
            class Broken(_Cursor):
                def execute(self, sql, params=None):
                    raise RuntimeError("connection lost")
            return Broken(self.log)
        return _Cursor(self.log)

    def commit(self):
        self.log.append(("commit", ""))

    def rollback(self):
        self.log.append(("rollback", ""))

    def close(self):
        self.closed = True


def _statements(conn):
    return [s for kind, s in conn.log if kind == "sql"]


def test_the_lock_is_taken_before_the_work_and_released_after():
    conn = _Conn()
    with whatsapp._one_at_a_time(conn, "919826080207"):
        conn.log.append(("work", ""))
    kinds = [k if k != "sql" else s.split("(")[0].split()[-1] for k, s in conn.log]
    assert kinds.index("pg_advisory_lock") < kinds.index("work") < kinds.index("pg_advisory_unlock")


def test_the_lock_is_released_when_the_work_fails():
    """A voice note that fails to transcribe must not leave him locked out of
    every message after it."""
    conn = _Conn()
    with pytest.raises(ValueError):
        with whatsapp._one_at_a_time(conn, "919826080207"):
            raise ValueError("transcription refused")
    assert any("pg_advisory_unlock" in s for s in _statements(conn))


def test_a_failed_transaction_is_rolled_back_before_unlocking():
    """Postgres refuses every statement in a failed transaction, the unlock
    included, until it is rolled back."""
    conn = _Conn()
    with whatsapp._one_at_a_time(conn, "919826080207"):
        pass
    order = [k if k != "sql" else s for k, s in conn.log]
    unlock_at = next(i for i, e in enumerate(order) if "pg_advisory_unlock" in e)
    assert "rollback" in order[:unlock_at]


def test_a_connection_that_cannot_unlock_is_closed_not_reused():
    """If it went back to the pool still holding the lock, the next request to
    borrow it would hold this person's lock for good."""
    conn = _Conn(fail_unlock=True)
    with whatsapp._one_at_a_time(conn, "919826080207"):
        pass
    assert conn.closed


def test_the_lock_is_per_sender():
    """Different people must never wait on each other."""
    a, b = _Conn(), _Conn()
    with whatsapp._one_at_a_time(a, "919826080207"):
        pass
    with whatsapp._one_at_a_time(b, "919893351932"):
        pass
    # The sender is a parameter to the lock, not part of a fixed key.
    assert all("hashtext(%s)" in s for s in _statements(a) if "advisory" in s)


def test_every_message_goes_through_the_lock():
    import inspect

    source = inspect.getsource(whatsapp._process_message)
    assert "_one_at_a_time" in source
    assert source.index("_one_at_a_time") < source.index("_dispatch(")
