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


# Meta's limits on an interactive message. A body longer than this is refused
# outright, which is why a readback is sent as ordinary text first and the
# buttons follow in a short message of their own.
BUTTON_BODY_LIMIT = 1024
BUTTON_LABEL_LIMIT = 20
MAX_BUTTONS = 3


def send_buttons(to: str, body: str, buttons: list) -> str | None:
    """A message with tappable replies. `buttons` is [(id, label)].

    Tapping one comes back through the webhook as an interactive message
    carrying the id, so the id has to say what the tap means - a meeting to
    confirm, for instance. It is never shown to the reader."""
    url = f"{_GRAPH}/{GRAPH_VERSION}/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:BUTTON_BODY_LIMIT]},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": bid, "title": label[:BUTTON_LABEL_LIMIT]}}
                for bid, label in buttons[:MAX_BUTTONS]
            ]},
        },
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


def send_template(to: str, template: str, language: str = "en_US") -> str | None:
    """Open a conversation, rather than reply inside one.

    WhatsApp only allows free-form text within 24 hours of the person's last
    message. Outside that window Meta accepts the send, hands back a real
    message id, and drops the message - which is how two messages were reported
    as sent and never reached a phone. A pre-approved template is the only thing
    that gets through, and sending one re-opens the window for 24 hours, so a
    real message can follow it.

    The template must already be approved in the WhatsApp Manager; an unknown
    name is refused by Meta rather than delivered as its own text."""
    url = f"{_GRAPH}/{GRAPH_VERSION}/{os.environ['WHATSAPP_PHONE_NUMBER_ID']}/messages"
    payload = json.dumps({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {"name": template, "language": {"code": language}},
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
