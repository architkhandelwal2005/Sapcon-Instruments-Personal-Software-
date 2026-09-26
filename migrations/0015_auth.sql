-- The web app has had no login at all while holding ~700 customer contacts with
-- phone numbers and email addresses, on an address that must be reachable from
-- the internet for the WhatsApp webhook. This adds sign-in.
--
-- A person already exists as an entities row (entity_type='employee'), so a
-- credential is keyed to that row - there is no second identity system.

create table app_users (
  entity_id        uuid primary key references entities(id) on delete cascade,
  phone_digits     text not null unique,       -- app.phone.normalize_phone form
  pin_hash         text,                       -- null until they enrol
  pin_set_at       timestamptz,
  role             text not null check (role in ('owner', 'office', 'employee')),
  enrol_code_hash  text,                       -- one-time code, hashed
  enrol_expires_at timestamptz,
  failed_attempts  int not null default 0,
  locked_until     timestamptz,
  last_login_at    timestamptz,
  disabled         boolean not null default false,
  created_at       timestamptz default now()
);

-- Sessions live here rather than in a signed cookie, so signing out and
-- revoking access actually work and there is no secret key to manage. Only the
-- hash of the cookie value is stored: a copy of this table cannot be used to
-- impersonate anyone.
create table app_sessions (
  token_hash   text primary key,
  entity_id    uuid not null references entities(id) on delete cascade,
  created_at   timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  expires_at   timestamptz not null,
  user_agent   text
);

create index app_sessions_entity_idx  on app_sessions (entity_id);
create index app_sessions_expires_idx on app_sessions (expires_at);

-- Who confirmed or rejected what. Append-only, so a reject and a later restore
-- both survive - which two columns on each table could not express.
create table review_decisions (
  id         bigserial primary key,
  kind       text not null,          -- relation | task | decision | entity
  item_id    uuid not null,
  decision   text not null,          -- confirm | reject
  decided_by uuid references entities(id),   -- null for scripts and older rows
  decided_at timestamptz not null default now(),
  note       text
);

create index review_decisions_item_idx on review_decisions (kind, item_id, decided_at desc);

-- whatsapp_senders.phone is unique on the literal string, so '+919893351932'
-- and '919893351932' are two rows, and the webhook's digit comparison could not
-- use the index anyway. This makes the digits themselves unique and indexed.
create unique index whatsapp_senders_digits_idx
  on whatsapp_senders ((regexp_replace(phone, '\D', '', 'g')));
