"""Send somebody a message, whether or not they have written recently.

WhatsApp lets a business send free text only within 24 hours of that person's
last message to it. Outside that window Meta accepts the send, returns a real
message id, and drops the message - so "sent" looked identical to "arrived",
and two real messages vanished that way.

This says which case it is before sending, and when the window is shut it sends
an approved template first. A template re-opens the window, so the real message
can follow it a moment later.

Usage:
    reach_out.py <phone>                      # say whether the window is open
    reach_out.py <phone> --text "..."         # send, if the window is open
    reach_out.py <phone> --text "..." --open  # open it with a template first
    reach_out.py <phone> --text-file note.txt
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.db import get_connection, release_connection
from app.phone import normalize_phone
from app.whatsapp.client import send_template, send_whatsapp
from app.whatsapp.delivery import last_failure, record_sent

# Meta ships this one with every new number, so it always exists. Replace it
# with your own approved template once you have one.
DEFAULT_TEMPLATE = "hello_world"

WINDOW_HOURS = 24


def _window_open(conn, digits: str) -> tuple[bool, str]:
    """Whether they have written to us within the window, and when last."""
    with conn.cursor() as cur:
        cur.execute(
            "select max(created_at) from conversation_turns where sender = %s and role = 'them'",
            (digits,),
        )
        (last,) = cur.fetchone()
    conn.rollback()
    if last is None:
        return False, "they have never written to this number (or not since the bot started recording)"
    age_hours = (time.time() - last.timestamp()) / 3600
    if age_hours < WINDOW_HOURS:
        return True, f"they wrote {age_hours:.1f} hours ago"
    return False, f"they last wrote {age_hours / 24:.1f} days ago"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phone")
    parser.add_argument("--text")
    parser.add_argument("--text-file")
    parser.add_argument("--open", action="store_true",
                        help="send a template first when the window is shut")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE)
    args = parser.parse_args()

    digits = normalize_phone(args.phone)
    body = args.text or (Path(args.text_file).read_text(encoding="utf-8") if args.text_file else None)

    conn = get_connection()
    try:
        open_now, why = _window_open(conn, digits)
        print(f"{digits}: window {'OPEN' if open_now else 'SHUT'} - {why}")

        failure = last_failure(conn, digits)
        if failure:
            print(f"  last failed delivery: {failure['error_code']} - {failure['reason']}")

        if not body:
            return

        if not open_now:
            if not args.open:
                print("\nNot sending: free text would be accepted by Meta and then dropped.")
                print("Either ask them to send any message first, or re-run with --open.")
                return
            template_id = send_template(digits, args.template)
            record_sent(conn, template_id, digits)
            print(f"  template '{args.template}' sent ({template_id}) - waiting for the window")
            time.sleep(5)

        message_id = send_whatsapp(digits, body)
        record_sent(conn, message_id, digits)
        print(f"  message sent ({message_id})")
        print("\nAccepted by Meta. Whether it arrived shows up as a delivery status on the")
        print("webhook within a minute - check whatsapp_deliveries, not this output.")
    finally:
        release_connection(conn)


if __name__ == "__main__":
    main()
