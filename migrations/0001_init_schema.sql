-- Core schema for Sapcon relationship CRM.

create extension if not exists pgcrypto;

create table entities (
  id uuid primary key default gen_random_uuid(),
  canonical_name text not null,
  entity_type text not null,     -- person | company | site
  aliases text[] default '{}'
);

create table meetings (
  id uuid primary key default gen_random_uuid(),
  meeting_date date not null,
  primary_contact_id uuid references entities(id),
  location text,
  raw_transcript text,
  audio_url text,
  created_at timestamptz default now()
);

create table relations (
  id uuid primary key default gen_random_uuid(),
  source_id uuid references entities(id),
  target_id uuid references entities(id),
  relation_type text not null,
  meeting_id uuid references meetings(id),
  provenance text,                -- direct | hearsay
  status text default 'active',   -- active | superseded | disputed
  recorded_at date not null
);

create table tasks (
  id uuid primary key default gen_random_uuid(),
  description text not null,
  related_entity_id uuid references entities(id),
  assigned_to uuid,   -- will reference a users table once multi-user exists; nullable for now
  meeting_id uuid references meetings(id),
  due_date date,
  status text default 'open'   -- open | done | overdue
);
