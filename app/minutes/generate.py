import psycopg


def generate_minutes(conn: psycopg.Connection, meeting_id: str) -> str:
    """Render a meeting's stored relations/tasks into readable minutes.

    This is a pure formatter over rows already in the DB - no LLM call, no
    independent summarization of the transcript. The minutes can never say
    anything the graph doesn't already contain: if something's missing here,
    it's missing from the graph, not just from this summary, so a correction
    made from reading the minutes fixes the real data.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            select m.meeting_date, m.location, m.audio_url, m.raw_transcript, pc.canonical_name
            from meetings m
            left join entities pc on pc.id = m.primary_contact_id
            where m.id = %s
            """,
            (meeting_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"No meeting found with id {meeting_id}")
        meeting_date, location, audio_url, raw_transcript, primary_contact_name = row

        cur.execute(
            """
            select e1.canonical_name, r.relation_type, e2.canonical_name, r.provenance
            from relations r
            join entities e1 on e1.id = r.source_id
            join entities e2 on e2.id = r.target_id
            where r.meeting_id = %s and r.status = 'active'
            order by (r.provenance = 'hearsay'), e1.canonical_name
            """,
            (meeting_id,),
        )
        relations = cur.fetchall()

        cur.execute(
            """
            select t.description, e.canonical_name, t.due_date, t.status
            from tasks t
            left join entities e on e.id = t.related_entity_id
            where t.meeting_id = %s
            order by t.due_date nulls last
            """,
            (meeting_id,),
        )
        tasks = cur.fetchall()

    lines = [
        "MEETING MINUTES",
        f"Meeting ID     : {meeting_id}",
        f"Date           : {meeting_date}",
        f"Primary contact: {primary_contact_name or '(none)'}",
        f"Location       : {location or '(not recorded)'}",
    ]
    if audio_url:
        lines.append(f"Audio file     : {audio_url}")

    lines += ["", "RELATIONSHIPS"]
    direct = [r for r in relations if r[3] == "direct"]
    hearsay = [r for r in relations if r[3] == "hearsay"]
    if direct:
        lines.append("  Direct:")
        lines += [f"    - {source} {relation_type} {target}" for source, relation_type, target, _ in direct]
    if hearsay:
        lines.append("  Hearsay (unverified):")
        lines += [f"    - {source} {relation_type} {target}" for source, relation_type, target, _ in hearsay]
    if not relations:
        lines.append("  (none extracted)")

    lines += ["", "TASKS"]
    if tasks:
        for description, related_name, due_date, status in tasks:
            due_str = f"due {due_date}" if due_date else "no due date"
            ref = f" -- re: {related_name}" if related_name else ""
            marker = "x" if status == "done" else " "
            lines.append(f"  [{marker}] {description} ({due_str}){ref}")
    else:
        lines.append("  (none extracted)")

    lines += [
        "",
        "-" * 70,
        "RAW TRANSCRIPT (check the above against this -- if something's missing above,",
        "it's missing from the graph, not just this summary; correct it with a follow-up",
        "voice note appended to this meeting)",
        "",
        raw_transcript or "(no transcript stored)",
    ]

    return "\n".join(lines)


def store_minutes(conn: psycopg.Connection, meeting_id: str) -> str:
    minutes = generate_minutes(conn, meeting_id)
    with conn.cursor() as cur:
        cur.execute(
            "update meetings set minutes = %s, minutes_generated_at = now() where id = %s",
            (minutes, meeting_id),
        )
    return minutes
