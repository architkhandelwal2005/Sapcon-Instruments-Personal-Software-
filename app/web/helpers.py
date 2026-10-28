import subprocess
import sys
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
    data, mime = to_transcribable(data, path, audio.content_type or "audio/wav")
    return transcribe_audio(data, mime), path


# What Gemini reads directly. A phone browser records webm (Android) or mp4
# (iPhone), which it may not, so those are converted first.
TRANSCRIBABLE = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/aac",
                 "audio/ogg", "audio/flac", "audio/aiff", "audio/x-aiff"}


def to_transcribable(data: bytes, path: str, mime: str) -> tuple[bytes, str]:
    """(bytes, mime) in a format the transcriber accepts. Without ffmpeg, or if
    it fails, the original goes through unchanged - a refused format is a
    clearer error than a lost recording."""
    base = mime.split(";")[0].strip().lower()
    if base in TRANSCRIBABLE:
        return data, base
    out = path + ".mp3"
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path,
                        "-ac", "1", "-ar", "16000", "-b:a", "48k", out],
                       check=True, timeout=120)
        return Path(out).read_bytes(), "audio/mpeg"
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"could not convert {base} audio: {exc}", file=sys.stderr)
        return data, base


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
