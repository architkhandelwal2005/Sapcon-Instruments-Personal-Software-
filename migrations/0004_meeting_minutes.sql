-- Minutes are derived from relations/tasks, not a separate source of truth -
-- regenerated (not hand-edited) whenever a meeting's data changes, e.g. via
-- a correction voice note appending to it.
alter table meetings
  add column minutes text,
  add column minutes_generated_at timestamptz;
