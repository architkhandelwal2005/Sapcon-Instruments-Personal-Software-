-- A due date the system filled in because none was said. Shown as "assumed"
-- so nobody mistakes it for a deadline the owner actually set.
alter table tasks add column due_assumed boolean not null default false;

-- When each owner first opened the task. "Seen" answers "did Vishal even get
-- this?" without anyone having to ask him.
alter table task_assignees add column seen_at timestamptz;

-- What a won lead was worth, and why a lost one was lost.
alter table leads add column order_value numeric(14, 2);
alter table leads add column drop_reason text;

-- Once-a-day jobs (the morning email, the overdue check) record the day they
-- ran, so a restart or a second copy of the app cannot run them twice.
create table daily_runs (
  job text not null,
  day date not null,
  ran_at timestamptz not null default now(),
  primary key (job, day)
);

-- "Overdue by 3 days" is said once per task, not every morning.
create unique index notifications_overdue_once
  on notifications (recipient_id, kind, item_id) where kind = 'overdue';
