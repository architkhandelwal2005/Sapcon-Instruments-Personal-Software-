-- Meta answers a send with a message id, which means accepted, not delivered.
-- The real outcome arrives later as a status callback, and the webhook was
-- discarding those - so a message that Meta dropped (outside the 24-hour
-- window, number not reachable) looked exactly like one that arrived. Two real
-- messages were reported as sent and never existed on a phone.
create table whatsapp_deliveries (
  wa_message_id text primary key,
  recipient     text not null,
  status        text not null,          -- sent | delivered | read | failed
  error_code    int,
  error_title   text,
  sent_at       timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index whatsapp_deliveries_status_idx on whatsapp_deliveries (status)
  where status = 'failed';
