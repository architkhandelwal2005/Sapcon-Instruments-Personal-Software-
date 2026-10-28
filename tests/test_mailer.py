"""What a notification email says, and which failures are retried."""

import urllib.error

from app import mailer


def test_one_notice_is_its_own_subject():
    d = mailer.build_digest("Vishal Dixit", [("New task for you: send Parag quote", "/tasks/1")], "https://x")
    assert d.subject == "New task for you: send Parag quote"
    assert "Hi Vishal," in d.text
    assert "https://x/tasks/1" in d.text


def test_several_notices_become_one_email():
    d = mailer.build_digest("A B", [("one", "/tasks/1"), ("two", "/leads/2")], "https://x")
    assert d.subject.startswith("2 new notifications")
    assert "one" in d.text and "two" in d.text


def test_html_is_escaped():
    """A task description is typed by people; it must not become markup."""
    d = mailer.build_digest("A", [("<script>x</script>", "/tasks/1")], "https://x")
    assert "<script>" not in d.html


class _Conn:
    """Enough of a connection for flush(): records what was marked sent."""
    def __init__(self):
        self.marked = []
        self.committed = False

    def cursor(self):
        conn = self

        class C:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql, params=None): conn.marked.append(params[0])
        return C()

    def commit(self):
        self.committed = True


def _run(monkeypatch, error):
    monkeypatch.setattr(mailer, "_pending", lambda conn: {
        "e1": {"name": "Vishal", "email": "v@x.in", "ids": [1, 2], "items": [("hi", "/tasks/1")]}})
    def sender(*a):
        if error:
            raise error
    conn = _Conn()
    return mailer.flush(conn, "https://x", sender=sender), conn.marked


def test_a_sent_email_marks_its_notices(monkeypatch):
    assert _run(monkeypatch, None) == (1, [[1, 2]])


def test_a_network_failure_is_retried(monkeypatch):
    assert _run(monkeypatch, OSError("down")) == (0, [])


def test_a_bad_key_is_retried_not_dropped(monkeypatch):
    """401 is our setup, not this person's address - their notices must survive it."""
    err = urllib.error.HTTPError("u", 401, "unauthorized", {}, None)
    assert _run(monkeypatch, err) == (0, [])


def test_a_malformed_address_is_given_up(monkeypatch):
    err = urllib.error.HTTPError("u", 400, "bad", {}, None)
    assert _run(monkeypatch, err) == (0, [[1, 2]])
