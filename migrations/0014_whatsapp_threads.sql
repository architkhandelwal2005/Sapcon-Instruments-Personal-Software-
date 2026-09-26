-- When the owner replies to a readback on WhatsApp, Meta tells us which
-- message he replied to. That is an unambiguous, free signal that his words
-- belong to that meeting rather than being a new note or a question - so the
-- outbound message id has to be remembered to read it.
create table whatsapp_threads (
  wa_message_id    text primary key,                  -- the readback WE sent
  meeting_id       uuid not null references meetings(id) on delete cascade,
  sender_entity_id uuid references entities(id),
  sent_at          timestamptz not null default now()
);

create index whatsapp_threads_meeting_idx on whatsapp_threads (meeting_id);
