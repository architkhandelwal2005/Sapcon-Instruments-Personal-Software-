-- Internal office meetings (sales reviews, team briefings) alongside customer
-- field visits. An internal meeting produces attendees, decisions (targets,
-- policies, rankings) and tasks that can have several owners - none of which fit
-- the customer-graph shape of a field visit.

alter table meetings add column kind text not null default 'field_visit';
alter table meetings add constraint meetings_kind_check check (kind in ('field_visit', 'internal'));

-- Who was in the room. `name` is kept exactly as heard; employee_id is set only
-- when it confidently matched someone on the roster - never guessed.
create table meeting_attendees (
  id uuid primary key default gen_random_uuid(),
  meeting_id uuid not null references meetings(id) on delete cascade,
  name text not null,
  employee_id uuid references entities(id)
);
create index meeting_attendees_meeting_idx on meeting_attendees (meeting_id);

-- Things agreed or announced. Same confidence/review gate as relations and tasks.
create table decisions (
  id uuid primary key default gen_random_uuid(),
  meeting_id uuid not null references meetings(id) on delete cascade,
  description text not null,
  source_quote text,
  confidence text,
  review_status text not null default 'pending',
  created_at timestamptz default now()
);
create index decisions_meeting_idx on decisions (meeting_id);

-- A task can have several owners ("Saurabh and Sanjeevani will..."). Replaces the
-- single tasks.assigned_to column; an unmatched spoken name is kept (employee_id
-- null) so no assignment is ever silently lost.
create table task_assignees (
  id uuid primary key default gen_random_uuid(),
  task_id uuid not null references tasks(id) on delete cascade,
  name text not null,
  employee_id uuid references entities(id)
);
create index task_assignees_task_idx on task_assignees (task_id);
create index task_assignees_employee_idx on task_assignees (employee_id);

insert into task_assignees (task_id, name, employee_id)
select t.id, e.canonical_name, t.assigned_to
from tasks t join entities e on e.id = t.assigned_to
where t.assigned_to is not null;

alter table tasks drop column assigned_to;
