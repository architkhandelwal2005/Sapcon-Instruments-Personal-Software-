-- One row per submitted photo (a sheet of visiting cards, or a diary page), which
-- can contain several entities. Mirrors how relations/tasks reference meetings: an
-- umbrella event, child rows reference it so a reviewer can always get back to the
-- source image - handwriting can't self-verify the way a transcript quote can, so
-- the photo has to be kept, not just processed and discarded.

create table capture_events (
  id uuid primary key default gen_random_uuid(),
  capture_type text not null,         -- 'card' | 'diary'
  photo_url text not null,            -- Supabase Storage URL - the source, kept forever
  captured_date date not null,
  logged_by uuid references entities(id),
  raw_extraction jsonb,               -- full vision-model output, verbatim
  created_at timestamptz default now()
);

alter table entities add column capture_event_id uuid references capture_events(id);
-- leads inherit traceability through entity_id -> capture_event_id, no extra FK needed.
