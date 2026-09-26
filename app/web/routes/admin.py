"""Managing who can sign in. Owner only.

There is no channel to send a setup code on - the Meta test number accepts five
recipients in total - so the owner issues a code here and passes it to the
person himself. The code is shown once and only its hash is kept.
"""


from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection, release_connection
from app.phone import normalize_phone
from app.web.auth import ROLES, end_all_sessions, issue_enrol_code
from app.web.templating import templates

router = APIRouter()


def _users(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select u.entity_id, e.canonical_name, u.phone_digits, u.role,
                   u.pin_hash is not null, u.disabled, u.last_login_at,
                   u.enrol_expires_at > now(),
                   (select count(*) from app_sessions s where s.entity_id = u.entity_id
                                                         and s.expires_at > now())
            from app_users u join entities e on e.id = u.entity_id
            order by u.role, e.canonical_name
            """
        )
        rows = cur.fetchall()
    return [
        {"entity_id": str(r[0]), "name": r[1], "phone": r[2], "role": r[3], "has_pin": r[4],
         "disabled": r[5], "last_login_at": r[6], "code_pending": bool(r[7]), "sessions": r[8]}
        for r in rows
    ]


def _candidates(conn) -> list[dict]:
    """Employees who have no login yet."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select e.id, e.canonical_name, e.phone
            from entities e
            where e.entity_type = 'employee'
              and not exists (select 1 from app_users u where u.entity_id = e.id)
            order by e.canonical_name
            """
        )
        rows = cur.fetchall()
    return [{"entity_id": str(r[0]), "name": r[1], "phone": r[2] or ""} for r in rows]


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, code: str = "", code_for: str = "", error: str = ""):
    conn = get_connection()
    try:
        context = {"users": _users(conn), "candidates": _candidates(conn), "roles": ROLES,
                   "issued_code": code, "issued_for": code_for, "error": error,
                   "actor": request.state.actor}
    finally:
        release_connection(conn)
    return templates.TemplateResponse(request, "admin_users.html", context)


@router.post("/admin/users")
def add_user(entity_id: str = Form(...), phone: str = Form(...), role: str = Form(...)):
    if role not in ROLES:
        return RedirectResponse("/admin/users?error=Unknown+role", status_code=303)
    try:
        digits = normalize_phone(phone)
    except ValueError:
        return RedirectResponse("/admin/users?error=That+phone+number+looks+wrong", status_code=303)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "insert into app_users (entity_id, phone_digits, role) values (%s, %s, %s) "
                "on conflict (entity_id) do update set phone_digits = excluded.phone_digits, "
                "role = excluded.role",
                (entity_id, digits, role),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        release_connection(conn)
        return RedirectResponse("/admin/users?error=That+number+already+belongs+to+someone",
                                status_code=303)
    finally:
        if not conn.closed:
            release_connection(conn)
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{entity_id}/enrol-code")
def enrol_code(entity_id: str):
    """Issue a setup code. Shown once, on the page it redirects to."""
    conn = get_connection()
    try:
        code = issue_enrol_code(conn, entity_id)
        with conn.cursor() as cur:
            cur.execute("select canonical_name from entities where id = %s", (entity_id,))
            row = cur.fetchone()
        conn.rollback()
    finally:
        release_connection(conn)
    who = row[0] if row else ""
    return RedirectResponse(f"/admin/users?code={code}&code_for={who}", status_code=303)


@router.post("/admin/users/{entity_id}/disabled")
def set_disabled(entity_id: str, disabled: str = Form(...)):
    """Turning someone off also ends their open sessions - otherwise a live
    cookie keeps working for up to 90 days."""
    off = disabled == "1"
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("update app_users set disabled = %s where entity_id = %s", (off, entity_id))
        conn.commit()
        if off:
            end_all_sessions(conn, entity_id)
    finally:
        release_connection(conn)
    return RedirectResponse("/admin/users", status_code=303)
