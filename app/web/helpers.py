from datetime import date


def with_overdue_flags(tasks) -> list[dict]:
    today = date.today()
    out = []
    for t in tasks:
        out.append(
            {
                "description": t.description,
                "related_entity_name": t.related_entity_name,
                "related_entity_id": getattr(t, "related_entity_id", None),
                "due_date": t.due_date,
                "status": t.status,
                "overdue": bool(t.due_date and t.due_date < today and t.status != "done"),
            }
        )
    return out
