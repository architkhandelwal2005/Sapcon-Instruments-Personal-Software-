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
| `GEMINI_API_KEY` | your Gemini key - transcription always uses it, whatever `EXTRACTION_PROVIDER` says |
| `WHATSAPP_TOKEN` | access token from the Meta app (see below) |
| `WHATSAPP_PHONE_NUMBER_ID` | the sending number's id from the Meta app (not the phone number itself) |
| `WHATSAPP_APP_SECRET` | Meta app secret - used to check every webhook's signature |
| `WHATSAPP_VERIFY_TOKEN` | any random string you choose; paste the same one into the Meta webhook form |
| `GRAPH_API_VERSION` | optional, defaults to `v23.0` |
| `PUBLIC_BASE_URL` | the URL the host gave you in step 4 |

`WHATSAPP_ALLOWED_NUMBERS` from the original plan is superseded - senders are now
managed in the `whatsapp_senders` database table instead (one row per person, no
redeploy needed to add someone). See step 3 below.

## 2. Set up WhatsApp (Meta Cloud API)

Meta's own API, not Twilio: Twilio now requires a paid account for any WhatsApp
sender, while Meta gives a free test number, free webhooks and a monthly free
conversation allowance.

This is already done for Sapcon; the live values are:

| Thing | Value |
|---|---|
| Meta app | **Sapcon CRM**, app id `1410064287885344` |
| Business portfolio | **Sapcon Instruments**, id `1369988595326618` |
| WhatsApp Business Account (WABA) | `2547089955764456` |
| Test sending number | `+1 555 183-7965`, phone number id `1259522373920794` |
| System user (owns the permanent token) | **Sapcon CRM Bot**, id `61594702773005` |

To redo it from scratch (or for a second environment):

1. At developers.facebook.com, create an app with the **Connect with customers
   through WhatsApp** use case. It needs a **business portfolio** - create one at
   business.facebook.com first if the account has none, or app creation blocks at
   the Business step.
2. **Use case -> Step 1. Try it out** claims the free test number and shows its
   **Phone number ID** and **WhatsApp Business account ID**.
3. The token offered on that page is temporary (24 hours). For something that runs
   unattended, create a **System User** instead (Business settings -> Users ->
   System users), assign it the app *and* the WABA with full access, then
   **Generate token** with expiration **Never** and scopes
   `whatsapp_business_messaging` + `whatsapp_business_management`. That is
   `WHATSAPP_TOKEN`.
4. On the same Step 1 page, add each phone that will message the bot to the test
   number's recipient list (max 5; Meta sends that phone a code *over WhatsApp*,
   and it expires within about a minute).
5. **App settings -> Basic** holds the **App secret** - that is
   `WHATSAPP_APP_SECRET`. Reset it there if it ever leaks.
6. **Register the number on the Cloud API** before sending anything, or every send
   fails with `(#133010) Account not registered`:

   ```
   POST https://graph.facebook.com/v23.0/<phone-number-id>/register
   {"messaging_product": "whatsapp", "pin": "<any 6 digits>"}
   ```

7. Point the webhook at the deployed app - either in **Use case -> Step 2.
   Production setup -> Configure Webhooks** (callback URL
   `<PUBLIC_BASE_URL>/whatsapp/webhook`, verify token = `WHATSAPP_VERIFY_TOKEN`),
   or over the API, which also subscribes the `messages` field in one call:

   ```
   POST https://graph.facebook.com/v23.0/<app-id>/subscriptions
        ?access_token=<app-id>|<app-secret>
   object=whatsapp_business_account&fields=messages
   &callback_url=<PUBLIC_BASE_URL>/whatsapp/webhook&verify_token=<verify token>

   POST https://graph.facebook.com/v23.0/<waba-id>/subscribed_apps   # bearer token
   ```

   Both are needed: the first subscribes the app, the second subscribes the WABA
   to the app. The app answers Meta's `hub.challenge` handshake on that same URL.

Two things that look like faults but aren't:

- **The test number is not reachable from a phone's contact list** (555 numbers
  don't resolve in WhatsApp). The business has to open the conversation first -
  send the `hello_world` template to the recipient, then reply inside that thread.
- **While the app is unpublished, Meta only delivers webhooks for people with a
  role on the app** (admin, developer, tester). Adding the uncle means giving his
  Facebook account a tester role, or publishing the app.

Going live on the uncle's own number (instead of the test number) is a Meta
Business verification step later - it changes `WHATSAPP_PHONE_NUMBER_ID` and the
token, no code.

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
