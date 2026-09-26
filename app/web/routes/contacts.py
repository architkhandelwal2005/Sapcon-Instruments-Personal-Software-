from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection, release_connection
from app.review import finalise_meeting_status
from app.web.auth import actor_of
from app.web.templating import templates

router = APIRouter()

PAGE_SIZE = 30


def _filter_options(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("select distinct region from entities where region is not null order by region")
        regions = [r[0] for r in cur.fetchall()]
        cur.execute("select distinct source from entities where source is not null order by source")
        sources = [r[0] for r in cur.fetchall()]
        cur.execute("select distinct role_tag from relations where role_tag is not null order by role_tag")
        roles = [r[0] for r in cur.fetchall()]
    return {"regions": regions, "sources": sources, "roles": roles}


def _predicate(*, q, etype, region, role, source) -> tuple[str, dict]:
    """The WHERE clause shared by the listing, the count, and bulk confirm -
    so all three act on exactly the same set."""
    where = ["e.review_status <> 'rejected'"]
    params: dict = {}
    if q:
        where.append(
            "(e.canonical_name ilike %(q)s or exists (select 1 from unnest(e.aliases) a where a ilike %(q)s))"
        )
        params["q"] = f"%{q}%"
    if etype:
        where.append("e.entity_type = %(etype)s")
        params["etype"] = etype
    if region:
        where.append("e.region = %(region)s")
        params["region"] = region
    if source:
        where.append("e.source = %(source)s")
        params["source"] = source
    if role:
        where.append(
            "exists (select 1 from relations r where (r.source_id = e.id or r.target_id = e.id) "
            "and r.role_tag = %(role)s and r.review_status <> 'rejected')"
        )
        params["role"] = role
    return " and ".join(where), params


def _search(conn, clause, params, page) -> tuple[list[dict], int, int]:
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from entities e where {clause}", params)
        total = cur.fetchone()[0]
        cur.execute(f"select count(*) from entities e where {clause} and e.review_status = 'pending'", params)
        pending = cur.fetchone()[0]
        cur.execute(
            f"""
            select e.id, e.canonical_name, e.entity_type, e.title, e.region, e.source, e.review_status
            from entities e
            where {clause}
            order by e.canonical_name
            limit %(limit)s offset %(offset)s
            """,
            {**params, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
        )
        rows = [
            {
                "id": str(i), "canonical_name": n, "entity_type": t, "title": ti,
                "region": rg, "source": src, "review_status": rs,
            }
            for i, n, t, ti, rg, src, rs in cur.fetchall()
        ]
    return rows, total, pending


@router.get("/contacts", response_class=HTMLResponse)
def contacts_page(
    request: Request,
    q: Optional[str] = None,
    type: Optional[str] = None,
    region: Optional[str] = None,
    role: Optional[str] = None,
    source: Optional[str] = None,
    page: int = 0,
    confirmed: Optional[int] = None,
):
    q = (q or "").strip()
    page = max(0, page)
    clause, params = _predicate(q=q, etype=type, region=region, role=role, source=source)

    conn = get_connection()
    try:
        options = _filter_options(conn)
        rows, total, pending = _search(conn, clause, params, page)
    finally:
        release_connection(conn)

    active = {"q": q, "type": type or "", "region": region or "", "role": role or "", "source": source or ""}
    prefix = urlencode({k: v for k, v in active.items() if v})
    prefix = f"{prefix}&" if prefix else ""
    return templates.TemplateResponse(
        request,
        "contacts.html",
        {
            "rows": rows,
            "total": total,
            "pending": pending,
            "page": page,
            "showing_from": page * PAGE_SIZE + 1 if rows else 0,
            "showing_to": page * PAGE_SIZE + len(rows),
            "prev_url": f"/contacts?{prefix}page={page - 1}" if page > 0 else None,
            "next_url": f"/contacts?{prefix}page={page + 1}" if (page + 1) * PAGE_SIZE < total else None,
            "options": options,
            "active": active,
            "confirmed": confirmed,
        },
    )


@router.post("/contacts/confirm")
def bulk_confirm(
    request: Request,
    q: str = Form(default=""),
    type: str = Form(default=""),
    region: str = Form(default=""),
    role: str = Form(default=""),
    source: str = Form(default=""),
):
    """Confirm every pending contact matching the current filter, plus their
    'employer' relations - how the office boy clears the seeded import once
    they have eyeballed a slice of it."""
    actor = actor_of(request)
    clause, params = _predicate(
        q=q.strip(), etype=(type or None), region=(region or None), role=(role or None), source=(source or None)
    )
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"update entities e set review_status = 'confirmed' where {clause} and e.review_status = 'pending' returning e.id",
                params,
            )
            confirmed_ids = [r[0] for r in cur.fetchall()]
            if confirmed_ids:
                cur.execute(
                    "update relations set review_status = 'confirmed' "
                    "where review_status = 'pending' and (source_id = any(%s) or target_id = any(%s))",
                    (confirmed_ids, confirmed_ids),
                )
                cur.execute(
                    "select distinct meeting_id from relations where meeting_id is not null "
                    "and (source_id = any(%s) or target_id = any(%s))",
                    (confirmed_ids, confirmed_ids),
                )
                affected_meetings = [r[0] for r in cur.fetchall()]
                # One audit row per contact. A thousand rows from one click is
                # the record worth having: who confirmed that import, and when.
                cur.executemany(
                    "insert into review_decisions (kind, item_id, decision, decided_by, note) "
                    "values ('entity', %s, 'confirm', %s, 'bulk confirm from /contacts')",
                    [(eid, actor.entity_id) for eid in confirmed_ids],
                )
            else:
                affected_meetings = []
        for m in affected_meetings:
            finalise_meeting_status(conn, m)
        conn.commit()
    finally:
        release_connection(conn)

    active = {"q": q.strip(), "type": type, "region": region, "role": role, "source": source}
    qs = urlencode({k: v for k, v in active.items() if v})
    sep = "&" if qs else ""
    return RedirectResponse(f"/contacts?{qs}{sep}confirmed={len(confirmed_ids)}", status_code=303)
