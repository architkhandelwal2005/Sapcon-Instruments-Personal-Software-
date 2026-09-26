from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.db import get_connection, release_connection
from app.query import ask as run_ask
from app.query import brief as run_brief
from app.query import connect as run_connect
from app.web.templating import templates

router = APIRouter()


@router.get("/ask", response_class=HTMLResponse)
def ask_page(
    request: Request,
    q: Optional[str] = None,
    entity: Optional[str] = None,
    a: Optional[str] = None,
    b: Optional[str] = None,
):
    ctx: dict = {"q": q or "", "heading": None, "answer": None, "understood": None}

    if not (entity or (a and b) or (q and q.strip())):
        return templates.TemplateResponse(request, "ask.html", ctx)  # just the form

    conn = get_connection()
    try:
        if entity:
            name, answer = run_brief(conn, entity)
            ctx["heading"] = f"Brief: {name}"
            ctx["answer"] = answer
        elif a and b:
            a_name, b_name, answer = run_connect(conn, a, b)
            ctx["heading"] = f"{a_name} & {b_name}"
            ctx["answer"] = answer
        elif q and q.strip():
            result = run_ask(conn, q.strip())
            ctx["answer"] = result.answer
            if result.entities:
                names = ", ".join(n for _, n in result.entities)
                label = {"brief": "briefing on", "connect": "connection between", "general": "about"}[result.mode]
                ctx["understood"] = f"Read as: {label} {names}"
            else:
                ctx["understood"] = "No known contact matched - answered from recent meetings."
    finally:
        release_connection(conn)

    return templates.TemplateResponse(request, "ask.html", ctx)
