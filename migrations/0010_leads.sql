-- Leads: who owns each prospect and its status. No invented sales-funnel stages -
-- open/converted/dropped matches how the team actually works. Status only ever
-- changes by a human action (the uncle dropping it, or the assignee updating it);
-- "dropped" is a status, never a delete - full history stays, same as everywhere
-- else in this system nothing is silently destroyed.
--
-- No separate activity-log table: a call/update against a lead IS a meeting
-- (logged_by = the employee, primary_contact_id = the lead's contact) - already
-- fully built. A lead's activity history is the existing interaction-history query,
-- filtered to entity_id.

create table leads (
  id uuid primary key default gen_random_uuid(),
  entity_id uuid not null references entities(id),       -- the company/contact
  assigned_to uuid references entities(id),               -- employee; null until allotted
  status text not null default 'open',                    -- open | converted | dropped
  source text,                                             -- voice | diary | card | visit_list | manual
  next_follow_up_due date,
  notes text,
  created_at timestamptz default now(),
  status_changed_at timestamptz,
  status_changed_by uuid references entities(id)           -- audit: who changed it
);

create index leads_status_idx on leads (status);
create index leads_assigned_to_idx on leads (assigned_to);
create index leads_entity_idx on leads (entity_id);
