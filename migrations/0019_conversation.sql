-- The bot had no memory. Every message was judged alone, so "what about Parag?"
-- after a question about Rajesh meant nothing, and it could not refer to what it
-- had just said. A handful of recent turns per person is enough for that, and
-- small enough to send to the model on every message.
create table conversation_turns (
  id          bigserial primary key,
  sender      text not null,            -- wa_id digits
  role        text not null,            -- 'them' | 'us'
  body        text not null,
  created_at  timestamptz not null default now()
);
create index conversation_turns_sender_idx on conversation_turns (sender, created_at desc);
