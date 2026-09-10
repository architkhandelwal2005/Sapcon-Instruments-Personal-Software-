-- Accuracy-first redesign. See PLAN in the plan file. Synthetic/fixture rows
-- are truncated by scripts/reset_fixtures.py before this runs, so the column
-- repurposing on `relations` is clean.
--
-- Model: every AI-derived row carries a confidence and a review_status.
-- A second AI pass verifies each fact against the transcript and attaches
-- the supporting sentence (source_quote). high-confidence + verified rows
-- become 'auto_confirmed' (live, spot-checkable); everything else is
-- 'pending' until the office boy clears it. Entities are never silently
-- merged - an uncertain match creates a new row with possible_duplicate_of
-- set.

alter table entities
  add column confidence text,                       -- high | medium | low ; null for imported/manual
  add column review_status text default 'pending',  -- auto_confirmed | pending | confirmed | rejected
  add column possible_duplicate_of uuid references entities(id),
  add column notes text;

-- relations -> the plain-language connection model
alter table relations
  alter column relation_type drop not null,
  add column description text,       -- the plain-language sentence
  add column source_quote text,      -- verbatim transcript sentence supporting it
  add column confidence text,
  add column review_status text default 'pending';
alter table relations rename column relation_type to role_tag;   -- now nullable, set only when unambiguous
alter index relations_type_idx rename to relations_role_tag_idx;

alter table tasks
  add column review_status text default 'pending',
  add column confidence text,
  add column source_quote text;

alter table meetings
  add column summary text,                          -- LLM prose recap, used for query-time retrieval
  add column review_status text default 'pending',  -- pending while any item on the meeting is pending, else 'clear'
  add column reviewed_at timestamptz;

create index entities_review_status_idx on entities (review_status) where review_status = 'pending';
create index relations_review_status_idx on relations (review_status) where review_status = 'pending';
create index tasks_review_status_idx on tasks (review_status) where review_status = 'pending';
create index meetings_review_status_idx on meetings (review_status) where review_status = 'pending';
