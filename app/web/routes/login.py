"""Signing in, signing out, and setting a first PIN.

These are the only pages reachable without a session, so they are deliberately
small: a phone number, a PIN, and nothing that reads customer data.
"""

from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection, release_connection
from app.web.auth import (
    COOKIE_NAME,
    MIN_PIN_LENGTH,
    SESSION_DAYS,
    authenticate,
    complete_enrolment,
    end_session,
    new_session,
)
from app.web.templating import templates

router = APIRouter()

_MESSAGES = {
    "bad": "That phone number and PIN don't match.",
    "locked": "Too many wrong tries. Try again in a few minutes.",
    "not_enrolled": "This number has no PIN yet - ask for a setup code.",
    "disabled": "This account has been turned off.",
    "weak_pin": f"Choose a PIN of at least {MIN_PIN_LENGTH} digits.",
    "enrolled": "PIN set. Signed in.",
}


def _safe_next(raw: str) -> str:
    """Only ever redirect inside this app - an absolute URL here would make the
    login page an open redirect."""
    target = (raw or "/").strip()
    return target if target.startswith("/") and not target.startswith("//") else "/"


def _set_cookie(response, token: str):
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_DAYS * 24 * 3600,
        httponly=True, secure=True, samesite="lax", path="/",
    )
    return response


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/", error: str = ""):
    return templates.TemplateResponse(
        request, "login.html",
        {"next": _safe_next(next), "message": _MESSAGES.get(error, ""), "min_pin": MIN_PIN_LENGTH},
    )


@router.post("/login")
def login_submit(request: Request, phone: str = Form(...), pin: str = Form(...),
                 next: str = Form(default="/")):
    target = _safe_next(next)
    conn = get_connection()
    try:
        actor, reason = authenticate(conn, phone, pin)
        if actor is None:
            return RedirectResponse(f"/login?next={quote(target)}&error={reason}", status_code=303)
        token = new_session(conn, actor.entity_id, request.headers.get("user-agent", ""))
    finally:
        release_connection(conn)
    return _set_cookie(RedirectResponse(target, status_code=303), token)


@router.post("/logout")
def logout(request: Request):
    conn = get_connection()
    try:
        end_session(conn, request.cookies.get(COOKIE_NAME))
    finally:
        release_connection(conn)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@router.get("/enrol", response_class=HTMLResponse)
def enrol_form(request: Request, error: str = ""):
    return templates.TemplateResponse(
        request, "enrol.html", {"message": _MESSAGES.get(error, ""), "min_pin": MIN_PIN_LENGTH},
    )


@router.post("/enrol")
def enrol_submit(request: Request, phone: str = Form(...), code: str = Form(...),
                 pin: str = Form(...), pin_again: str = Form(...)):
    if pin != pin_again:
        return RedirectResponse("/enrol?error=bad", status_code=303)
    conn = get_connection()
    try:
        actor, reason = complete_enrolment(conn, phone, code, pin)
        if actor is None:
            return RedirectResponse(f"/enrol?error={reason}", status_code=303)
        token = new_session(conn, actor.entity_id, request.headers.get("user-agent", ""))
    finally:
        release_connection(conn)
    return _set_cookie(RedirectResponse("/tasks", status_code=303), token)
