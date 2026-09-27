"""Signing in, signing out, and choosing a first PIN.

These are the only pages reachable without a session, so they are deliberately
small: a phone number, a PIN, and nothing that reads customer data.

There is one door. Everyone types their phone number and their PIN at /login;
somebody signing in for the first time is sent on to choose one, with the
number they just typed carried across. Nobody has to be told which page to
start on, and nobody needs a code from anyone else.
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
    claim_account,
    end_session,
    new_session,
)
from app.web.templating import templates

router = APIRouter()

_MESSAGES = {
    "bad": "That phone number and PIN don't match.",
    "locked": "Too many wrong tries. Try again in a few minutes.",
    "disabled": "This account has been turned off.",
    "weak_pin": f"Choose a PIN of at least {MIN_PIN_LENGTH} digits.",
    "mismatch": "The two PINs were different. Try again.",
    "not_registered": "We don't have that number yet. Ask the office to add you, "
                      "then register here.",
    "already_set": "This number already has a PIN. Sign in with it, or ask for a reset.",
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
        if reason == "no_pin_yet":
            # First time on a number the owner registered: let them set the PIN
            # they just typed, rather than bouncing them to find another page.
            return RedirectResponse(
                f"/enrol?phone={quote(phone.strip())}&next={quote(target)}", status_code=303)
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
def enrol_form(request: Request, error: str = "", phone: str = "", next: str = "/"):
    return templates.TemplateResponse(
        request, "enrol.html",
        {"message": _MESSAGES.get(error, ""), "min_pin": MIN_PIN_LENGTH,
         "phone": phone, "next": _safe_next(next)},
    )


@router.post("/enrol")
def enrol_submit(request: Request, phone: str = Form(...), pin: str = Form(...),
                 pin_again: str = Form(...), next: str = Form(default="/")):
    target = _safe_next(next)
    back = f"/enrol?phone={quote(phone.strip())}&next={quote(target)}"
    if pin != pin_again:
        return RedirectResponse(f"{back}&error=mismatch", status_code=303)
    conn = get_connection()
    try:
        actor, reason = claim_account(conn, phone, pin)
        if actor is None:
            if reason == "already_set":
                return RedirectResponse(
                    f"/login?next={quote(target)}&error=already_set", status_code=303)
            return RedirectResponse(f"{back}&error={reason}", status_code=303)
        token = new_session(conn, actor.entity_id, request.headers.get("user-agent", ""))
    finally:
        release_connection(conn)
    return _set_cookie(RedirectResponse(target, status_code=303), token)
