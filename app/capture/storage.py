"""Photo storage for card/diary captures. A capture item can only be verified by a
human looking at the source image next to the extraction (handwriting can't
self-verify the way a transcript quote can), so the photo has to be kept, not just
processed and discarded.

Uses the object path (a random UUID, never listed or guessable) as the access
control - the same model every other page in this app already relies on (a
meeting/entity/lead URL is just an unguessable id, no login). Real customer contact
details are visible to anyone who gets the link, same exposure class as a meeting
transcript already is today.
"""

import os

BUCKET = "capture-photos"

# Voice notes live here for the same reason, arrived at the harder way: the
# recording was written to a temp file on a host whose disk is wiped on every
# restart, and transcription ran before anything was recorded anywhere. When
# the model refused - which it did, to a real 1:23 note - there was no row, no
# retry and no trace. A voice note is a minute of somebody's day standing
# outside a customer's office; it is not a thing to hold only in memory.
AUDIO_BUCKET = "voice-notes"


def _client():
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def upload(data: bytes, mime_type: str, object_name: str, bucket: str = BUCKET) -> str:
    """Upload one file, return its public URL. object_name should be an
    unguessable id (e.g. a uuid) - never a predictable name, because the
    unguessable path is the access control."""
    client = _client()
    try:
        client.storage.create_bucket(bucket, options={"public": True})
    except Exception:
        pass  # already exists - fine, this is a no-op safety net, not the happy path
    client.storage.from_(bucket).upload(
        object_name, data, {"content-type": mime_type, "upsert": "true"}
    )
    return client.storage.from_(bucket).get_public_url(object_name)


def upload_photo(image_bytes: bytes, mime_type: str, object_name: str) -> str:
    return upload(image_bytes, mime_type, object_name)


def upload_audio(audio_bytes: bytes, mime_type: str, object_name: str) -> str:
    return upload(audio_bytes, mime_type, object_name, bucket=AUDIO_BUCKET)


def download(url: str) -> bytes:
    """Fetch something back out, for a retry. The URL is public, so this needs
    no credentials - the same link the review screen uses."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()
