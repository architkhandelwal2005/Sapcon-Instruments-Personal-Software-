"""Who can open what. These are the rules an employee leaving the company
would otherwise take the contact book out through, so they are pinned."""

import pytest

from app.web.auth import Actor
from app.web.policy import allowed_roles, is_public, role_allows

EMPLOYEE = Actor(entity_id="e1", name="Someone", role="employee")
OFFICE = Actor(entity_id="e2", name="Office", role="office")
OWNER = Actor(entity_id="e3", name="Owner", role="owner")


@pytest.mark.parametrize("path", ["/login", "/enrol", "/logout", "/whatsapp/webhook", "/static/style.css"])
def test_pages_needed_before_signing_in_are_public(path):
    assert is_public(path) is True


@pytest.mark.parametrize("path", ["/", "/tasks", "/contacts", "/review", "/admin/users", "/meetings"])
def test_everything_else_needs_a_session(path):
    assert is_public(path) is False


@pytest.mark.parametrize("path", ["/tasks", "/leads", "/meetings/new", "/captures/new"])
def test_an_employee_can_do_their_own_job(path):
    assert role_allows("employee", path)


@pytest.mark.parametrize("path", ["/contacts", "/meetings", "/ask", "/review", "/", "/admin/users"])
def test_an_employee_cannot_reach_the_whole_book(path):
    assert not role_allows("employee", path)


def test_a_single_meeting_is_open_to_an_employee_but_the_log_is_not():
    # The row check in the handler decides which single meetings; the log
    # itself lists every customer visit.
    assert role_allows("employee", "/meetings/abc-123")
    assert not role_allows("employee", "/meetings")


@pytest.mark.parametrize("role", ["office", "employee"])
def test_only_the_owner_administers_logins(role):
    assert not role_allows(role, "/admin/users")
    assert role_allows("owner", "/admin/users")


def test_an_unknown_path_is_owner_only():
    # Default-deny: a route added later is locked until someone decides.
    assert allowed_roles("/something/nobody/listed") == ("owner",)


def test_tasks_filter_is_forced_for_an_employee_not_merely_defaulted():
    from app.web.routes.tasks import _predicate

    clause, params = _predicate(status="open", assigned_to="somebody-else", actor=EMPLOYEE)
    assert params["assigned_to"] == EMPLOYEE.entity_id
    assert "somebody-else" not in str(params)


def test_leads_filter_is_forced_for_an_employee():
    from app.web.routes.leads import _predicate

    clause, params = _predicate(status=None, assigned_to="somebody-else", source=None, actor=EMPLOYEE)
    assert params["assigned_to"] == EMPLOYEE.entity_id


@pytest.mark.parametrize("actor", [OFFICE, OWNER])
def test_staff_keep_the_filters_they_asked_for(actor):
    from app.web.routes.tasks import _predicate

    _, params = _predicate(status="open", assigned_to="somebody-else", actor=actor)
    assert params["assigned_to"] == "somebody-else"


def test_history_is_narrowed_for_an_employee_and_not_for_staff():
    from app.web.authz import visible_meeting_clause

    clause, params = visible_meeting_clause(EMPLOYEE)
    assert "logged_by" in clause and params["viewer"] == EMPLOYEE.entity_id
    assert visible_meeting_clause(OWNER) == ("true", {})
