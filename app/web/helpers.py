import tempfile
from datetime import date
from pathlib import Path


async def save_and_transcribe(audio) -> tuple[str, str]:
    """Persist an UploadFile to a temp file and transcribe it via Gemini.
    Returns (transcript_text, temp_path); the caller keeps the path so it can
    be stored as the meeting's audio reference."""
    from app.llm import transcribe_audio

    data = await audio.read()
    suffix = Path(audio.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    return transcribe_audio(data, audio.content_type or "audio/wav"), path


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
                "review_status": getattr(t, "review_status", ""),
                "confidence": getattr(t, "confidence", None),
                "source_quote": getattr(t, "source_quote", None),
                "task_id": getattr(t, "task_id", ""),
                "assignees": getattr(t, "assignees", []),
            }
        )
    return out
