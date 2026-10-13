-- Who changed what, and what it was before.
--
-- Until now only review decisions were recorded. Marking a task done,
-- handing it to someone else, changing a lead's status or follow-up date left
-- no trace: a lead kept only its latest change, a task kept nothing at all. So
-- nobody could see who closed something or what it said before, and nothing
-- on the website could be undone.
--
-- One row per field changed. The previous value is what makes undo possible -
-- an undo writes `before` back - and it is also the history people read.
--
-- `before` and `after` are jsonb because the values differ in shape: a status
-- is text, a follow-up date is a date, a task's owners are a list of people.

create table change_log (
  id bigserial primary key,
  kind text not null,            -- 'task' | 'lead' | 'contact'
  item_id uuid not null,
  field text not null,           -- 'status', 'owners', 'phone', ...
  before jsonb,
  after jsonb,
  changed_by uuid references entities(id),
  changed_at timestamptz not null default now(),
  via text not null default 'website',   -- 'website' | 'whatsapp'
  undone_at timestamptz,
  undone_by uuid references entities(id)
);

create index change_log_item_idx on change_log (kind, item_id, changed_at desc);
