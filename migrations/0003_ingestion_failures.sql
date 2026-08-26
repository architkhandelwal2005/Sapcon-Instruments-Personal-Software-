-- Nothing about ingesting a meeting may fail silently: a dropped voice note
-- is a lost meeting the user won't know went missing. Every failed
-- extraction/resolution/write gets a row here instead of just an exception.
create table ingestion_failures (
  id uuid primary key default gen_random_uuid(),
  meeting_date date not null,
  audio_path text,
  raw_transcript text,
  error_type text not null,      -- rate_limit | network_error | api_error | validation_error | unknown_error
  error_message text not null,
  occurred_at timestamptz default now(),
  resolved boolean default false
);

create index ingestion_failures_unresolved_idx on ingestion_failures (occurred_at) where not resolved;
