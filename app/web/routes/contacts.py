from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import get_connection

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

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


def _search(conn, *, q, etype, region, role, source, page) -> tuple[list[dict], int]:
    where = ["e.review_status <> 'rejected'"]
    params: dict = {}
    if q:
        where.append(
            "(e.canonical_name ilike %(q)s or exists "
            "(select 1 from unnest(e.aliases) a where a ilike %(q)s))"
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

    clause = " and ".join(where)
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from entities e where {clause}", params)
        total = cur.fetchone()[0]
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
    return rows, total


@router.get("/contacts", response_class=HTMLResponse)
def contacts_page(
    request: Request,
    q: Optional[str] = None,
    type: Optional[str] = None,
    region: Optional[str] = None,
    role: Optional[str] = None,
    source: Optional[str] = None,
    page: int = 0,
):
    q = (q or "").strip()
    page = max(0, page)

    conn = get_connection()
    try:
        options = _filter_options(conn)
        rows, total = _search(
            conn, q=q, etype=type, region=region, role=role, source=source, page=page
        )
    finally:
        conn.close()

    active = {"q": q, "type": type or "", "region": region or "", "role": role or "", "source": source or ""}
    prefix = urlencode({k: v for k, v in active.items() if v})
    prefix = f"{prefix}&" if prefix else ""
    return templates.TemplateResponse(
        request,
        "contacts.html",
        {
            "rows": rows,
            "total": total,
            "page": page,
            "showing_from": page * PAGE_SIZE + 1 if rows else 0,
            "showing_to": page * PAGE_SIZE + len(rows),
            "prev_url": f"/contacts?{prefix}page={page - 1}" if page > 0 else None,
            "next_url": f"/contacts?{prefix}page={page + 1}" if (page + 1) * PAGE_SIZE < total else None,
            "options": options,
            "active": active,
        },
    )
