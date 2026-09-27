-- An instruction sent on WhatsApp can match more than one open task - "the
-- Rakesh task" really did match two. Rather than guess, the bot replies with a
-- numbered list and waits. This is the wait: the choices it offered, and what
-- to do once one is picked.
--
-- It also holds the undo of the last change, so "undo" in the chat puts a row
-- back exactly as it was rather than being a second instruction that has to be
-- matched all over again.
create table whatsapp_pending (
  wa_message_id text primary key,               -- the message WE sent
  sender_phone  text not null,
  kind          text not null check (kind in ('choice', 'undo')),
  payload       jsonb not null,                 -- the choices, or the undo token
  created_at    timestamptz not null default now()
);

create index whatsapp_pending_sender_idx on whatsapp_pending (sender_phone, created_at desc);
