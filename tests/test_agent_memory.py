"""Conversation memory. Shallow, and never able to take a reply down with it."""

from app.agent.memory import recent, remember_turn, render


class _Cursor:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        if sql.strip().lower().startswith("select"):
            self._rows = self.store["rows"]
        else:
            self.store["written"].append(params)
            self._rows = []

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows=()):
        self.store = {"rows": list(rows), "written": []}

    def cursor(self):
        return _Cursor(self.store)

    def commit(self):
        pass

    def rollback(self):
        pass


class _BrokenConn(_Conn):
    def cursor(self):
        raise RuntimeError("database gone")


def test_a_turn_is_stored_with_who_said_it():
    conn = _Conn()
    remember_turn(conn, "919826080207", "them", "Met Rajesh at Parag today")
    assert conn.store["written"] == [("919826080207", "them", "Met Rajesh at Parag today")]


def test_an_empty_turn_is_not_stored():
    conn = _Conn()
    remember_turn(conn, "919826080207", "them", "   ")
    assert conn.store["written"] == []


def test_losing_the_thread_never_takes_the_reply_down():
    """A failure here costs the thread of a conversation. It must never
    propagate - the reply and the record matter more than the memory."""
    remember_turn(_BrokenConn(), "919826080207", "them", "hello")
    assert recent(_BrokenConn(), "919826080207") == []


def test_history_reads_oldest_first():
    # stored newest-first by the query, reversed for reading
    conn = _Conn(rows=[("us", "two tasks are open"), ("them", "what is pending")])
    assert recent(conn, "x") == [("them", "what is pending"), ("us", "two tasks are open")]


def test_it_reads_as_a_conversation():
    rendered = render([("them", "what is pending with Thermo"), ("us", "Two tasks.")])
    assert rendered == "Them: what is pending with Thermo\nYou: Two tasks."


def test_the_first_message_says_so():
    assert render([]) == "(this is the first message)"
