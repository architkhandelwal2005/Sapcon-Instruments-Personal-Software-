# Deployment runbook

How to put the app on a real URL (so WhatsApp can reach it, and so you/the office
boy/the uncle can open it from any phone or browser) and wire up WhatsApp via
Twilio. Follow this once; after that, `git push` to `main` redeploys automatically
on Railway/Render.

## 1. Host the app (Railway or Render)

Either works the same way here - both build straight from the `Dockerfile` in this
repo.

1. Create an account, connect this GitHub repo.
2. Create a new service "from a Dockerfile" pointing at this repo's root (no build
   command needed - the Dockerfile handles it).
3. Set the environment variables below in the host's dashboard - **paste secrets
   there directly, never send them in chat**.
4. Deploy. The host gives you a public HTTPS URL, e.g. `https://sapcon-crm.up.railway.app`.
   That's your `PUBLIC_BASE_URL` (no trailing slash).

### Environment variables to set on the host

| Variable | Value |
|---|---|
| `DATABASE_URL` | same Supabase connection string already in your local `.env` |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | same as local `.env` |
| `EXTRACTION_PROVIDER` | `anthropic` - **must** be this before any real recording or photo is processed (the free Gemini tier must never see real customer data). Note: voice-note **transcription** itself always goes through Gemini regardless of this setting - Anthropic's API has no audio input. If full privacy is ever required, transcription needs its own change (a paid Gemini key, or a different audio-capable provider). |
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `TWILIO_ACCOUNT_SID` | from the Twilio console |
| `TWILIO_AUTH_TOKEN` | from the Twilio console |
| `TWILIO_WHATSAPP_NUMBER` | `whatsapp:+14155238886` for the sandbox (see below), or your dedicated number once you have one |
| `PUBLIC_BASE_URL` | the URL the host gave you in step 4 |

`WHATSAPP_ALLOWED_NUMBERS` from the original plan is superseded - senders are now
managed in the `whatsapp_senders` database table instead (one row per person, no
redeploy needed to add someone). See step 3 below.

## 2. Set up Twilio WhatsApp (sandbox, to start)

1. Create a free Twilio account at twilio.com.
2. In the console, go to **Messaging → Try it out → Send a WhatsApp message** - this
   gives you the sandbox number and a join code (e.g. "join giraffe-happy").
3. From the uncle's phone (and anyone else who should be able to text the bot), send
   that "join <code>" message to the sandbox number via WhatsApp once. This activates
   the sandbox for that phone number - it lasts a while but isn't permanent; Twilio
   will tell you if it needs renewing.
4. In the sandbox settings, set **"When a message comes in"** to:
   `<PUBLIC_BASE_URL>/whatsapp/webhook`, method `POST`.

A dedicated WhatsApp Business number (no join code, no sandbox banner) is a Twilio
console step for later - it needs a WhatsApp Business Profile review, doesn't
change any code here.

## 3. Add each phone number that's allowed to use the bot

Every sender must be a row in `whatsapp_senders`, pointing at their entity (an
employee, or the "Uncle (owner)" placeholder seeded by `scripts/seed_employees.py`).
Anyone not in this table is silently ignored - no reply, nothing written.

```sql
insert into whatsapp_senders (phone, entity_id, role)
values ('+91XXXXXXXXXX', '<entity id from the entities table>', 'owner');  -- or 'employee' / 'office'
```

Run this against the Supabase database (same connection as `DATABASE_URL`) for the
uncle's number and each employee's number once their real phone numbers are known.

## 4. How it behaves once live

- **Voice note or typed text** → logged as a new meeting, same pipeline as
  `/meetings/new`. Reply comes back with counts and a link.
- **Photo** → card/diary capture. Caption the photo with the word "diary" anywhere
  to mark it as a diary page; no caption (or anything else) defaults to a card
  sheet. Reply comes back with counts, allotment info, and a link.
- **A message starting with "ask"** → a lookup, not something to log - e.g.
  "ask brief me on Priya Nair" or "ask what's pending with Thermo".
- Every reply comes from the same sandbox/business number, straight in the same
  WhatsApp chat.

## 5. Redeploying

Both Railway and Render redeploy automatically on every push to `main` once
connected. No separate deploy step.
