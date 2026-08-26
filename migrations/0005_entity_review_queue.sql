-- Durable trace for entity resolution ambiguity that couldn't be resolved
-- interactively (e.g. a web-submitted correction): a new entity got created
-- rather than auto-linked, but it scored a medium-confidence match against
-- an existing one. This must be a queryable record, not just a log line -
-- the future review queue surfaces these for manual merge/confirm.
create table entity_review_queue (
  id uuid primary key default gen_random_uuid(),
  entity_id uuid not null references entities(id),
  possible_duplicate_of uuid not null references entities(id),
  mentioned_name text not null,
  entity_type text not null,
  created_at timestamptz default now(),
  resolved boolean default false
);

create index entity_review_queue_unresolved_idx on entity_review_queue (created_at) where not resolved;
