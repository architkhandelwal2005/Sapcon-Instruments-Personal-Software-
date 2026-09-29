-- Meta redelivers a webhook it is not sure we received, and it does not wait
-- long to decide that: a sleeping free instance takes about fifty seconds to
-- wake, which is long enough. One voice note arrived twice on 29 September and
-- was filed as two meetings, transcribed slightly differently each time, and
-- one question was answered twice in the same chat.
--
-- The message id Meta sends is stable across those retries, so claiming it once
-- is enough. The insert is the claim: whoever inserts the row does the work,
-- and a second delivery finds the row already there and stops.
create table whatsapp_inbound (
  wa_message_id text primary key,
  sender        text not null,
  received_at   timestamptz not null default now()
);
