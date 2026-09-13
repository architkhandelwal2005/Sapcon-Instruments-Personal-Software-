"""Thin wrapper over the Twilio WhatsApp API: send a reply, and download an
incoming media attachment (Twilio requires HTTP Basic Auth with the account
SID/token on every media URL - it isn't a public link).
"""

import base64
import os
import urllib.request


def send_whatsapp(to: str, body: str) -> None:
    """`to` is the WhatsApp-form address exactly as Twilio sent it in the
    incoming `From` field (e.g. "whatsapp:+91..."), so a reply always goes back
    to the same address it came from."""
    from twilio.rest import Client

    client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    client.messages.create(from_=os.environ["TWILIO_WHATSAPP_NUMBER"], to=to, body=body)


def download_media(url: str) -> bytes:
    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    auth = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()
