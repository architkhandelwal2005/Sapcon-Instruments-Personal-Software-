"""Thin wrapper over the WhatsApp Cloud API (Meta Graph API): verify an
incoming webhook's signature, send a reply, and download an incoming media
attachment (a two-step fetch - media id to a short-lived URL, then the bytes,
both with the access token).

Chosen over Twilio because Twilio now requires a paid account for any
WhatsApp sender, while Meta's own test number and webhooks are free.
"""

import hashlib
import hmac
import json
import os
import urllib.request

GRAPH_VERSION = os.environ.get("GRAPH_API_VERSION", "v23.0")
_GRAPH = "https://graph.facebook.com"


def _token() -> str:
    return os.environ["WHATSAPP_TOKEN"]


def _get(url: str, *, raw: bool) -> bytes | dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_token()}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
    return body if raw else json.loads(body)


def valid_signature(raw_body: bytes, header: str) -> bool:
    """X-Hub-Signature-256 is 'sha256=<hmac of the exact raw body>'. Compared
    in constant time - this is the only thing standing between the public
    internet and writing rows into the CRM."""
    secret = os.environ["WHATSAPP_APP_SECRET"].encode()
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    got = (header or "").removeprefix("sha256=")
    return hmac.compare_digest(expected, got)


def send_whatsapp(to: str, body: str) -> str | None:
    """`to` is the sender's wa_id exactly as the webhook reported it (digits,
    no plus), so a reply always goes back to the chat it came from.

    Returns the outbound message id, which is how a later reply to this exact
    message can be recognised as belonging to it. A message that sent fine but
    whose id could not be read returns None rather than failing the send."""
    url = f"{_GRAPH}/{GRAPH_VERSION}/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }).encode()
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    try:
        return json.loads(raw)["messages"][0]["id"]
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def download_media(media_id: str) -> tuple[bytes, str]:
    """Returns (bytes, mime_type). The mime type comes from Meta's metadata
    rather than the filename - voice notes arrive as audio/ogg; codecs=opus,
    and only the part before the semicolon is a usable media type."""
    meta = _get(f"{_GRAPH}/{GRAPH_VERSION}/{media_id}", raw=False)
    data = _get(meta["url"], raw=True)
    mime = (meta.get("mime_type") or "application/octet-stream").split(";")[0].strip()
    return data, mime
