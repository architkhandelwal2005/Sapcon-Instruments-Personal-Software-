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


def _client():
    from supabase import create_client

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def upload_photo(image_bytes: bytes, mime_type: str, object_name: str) -> str:
    """Upload one photo, return its public URL. object_name should be an unguessable
    id (e.g. the capture_event's own uuid) - never a predictable name."""
    client = _client()
    try:
        client.storage.create_bucket(BUCKET, options={"public": True})
    except Exception:
        pass  # already exists - fine, this is a no-op safety net, not the happy path
    client.storage.from_(BUCKET).upload(
        object_name, image_bytes, {"content-type": mime_type, "upsert": "true"}
    )
    return client.storage.from_(BUCKET).get_public_url(object_name)
