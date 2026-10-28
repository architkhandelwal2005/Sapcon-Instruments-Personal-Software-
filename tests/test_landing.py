"""Where a signed-in person lands on the home page."""

from fastapi.testclient import TestClient

import app.web.main as main
from app.web.auth import Actor


def _client(monkeypatch, role):
    monkeypatch.setattr(main, "get_connection", lambda: None)
    monkeypatch.setattr(main, "release_connection", lambda conn: None)
    monkeypatch.setattr(main, "load_actor", lambda conn, token: Actor("e1", "Anshul", role))
    return TestClient(main.app, follow_redirects=False)


def test_an_employee_lands_on_their_tasks_without_an_error(monkeypatch):
    """A "no access" message straight after signing in reads as a failed
    sign-in, and people signed in again and again."""
    response = _client(monkeypatch, "employee").get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/tasks"


def test_an_employee_is_still_kept_out_of_staff_pages(monkeypatch):
    response = _client(monkeypatch, "employee").get("/contacts")
    assert response.headers["location"].startswith("/tasks?error=")
