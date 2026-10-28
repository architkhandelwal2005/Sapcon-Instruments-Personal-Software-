-- Updates: a short running note on a task or a lead ("called, they want 5% off,
-- revising Monday"), written by whoever is working it. The record of what is
-- happening between "assigned" and "done".
create table updates (
  id bigserial primary key,
  kind text not null check (kind in ('task', 'lead')),
  item_id uuid not null,
  body text not null,
  author_id uuid references entities(id),
  created_at timestamptz not null default now()
);
create index updates_item_idx on updates (kind, item_id, created_at);

-- Notifications: what each signed-in person should hear about, shown behind
-- the bell. Delivery by WhatsApp can read the same rows later.
create table notifications (
  id bigserial primary key,
  recipient_id uuid not null references entities(id) on delete cascade,
  kind text not null,              -- assigned | status | update
  item_kind text not null,         -- task | lead
  item_id uuid not null,
  body text not null,
  url text not null,
  actor_id uuid references entities(id),
  created_at timestamptz not null default now(),
  read_at timestamptz
);
create index notifications_inbox_idx on notifications (recipient_id, created_at desc);
create index notifications_unread_idx on notifications (recipient_id) where read_at is null;

-- Being given a piece of work is news once. Owners are rewritten as a set when
-- one is added, and an undo can put an owner back; neither should ping again.
create unique index notifications_assigned_once
  on notifications (recipient_id, kind, item_id) where kind = 'assigned';

-- Assignments are announced by the database because work is handed out from
-- five places - voice notes, WhatsApp commands, card and diary photos, the
-- website, corrections - and a sixth added later must not quietly skip it.
-- Only people who can sign in are told; there is nowhere to show anyone else.

create function notify_task_assigned() returns trigger language plpgsql as $$
begin
  if new.employee_id is not null
     and exists (select 1 from app_users where entity_id = new.employee_id and not disabled) then
    insert into notifications (recipient_id, kind, item_kind, item_id, body, url)
    select new.employee_id, 'assigned', 'task', t.id,
           'New task for you: ' || left(t.description, 160), '/tasks/' || t.id
    from tasks t
    where t.id = new.task_id and t.review_status <> 'rejected' and t.status <> 'done'
    on conflict do nothing;
  end if;
  return new;
end $$;

create trigger task_assignees_notify
  after insert on task_assignees
  for each row execute function notify_task_assigned();

create function notify_lead_assigned() returns trigger language plpgsql as $$
begin
  if new.assigned_to is not null
     and (tg_op = 'INSERT' or new.assigned_to is distinct from old.assigned_to)
     and exists (select 1 from app_users where entity_id = new.assigned_to and not disabled) then
    insert into notifications (recipient_id, kind, item_kind, item_id, body, url)
    select new.assigned_to, 'assigned', 'lead', new.id,
           'New lead for you: ' || e.canonical_name, '/leads/' || new.id
    from entities e where e.id = new.entity_id
    on conflict do nothing;
  end if;
  return new;
end $$;

create trigger leads_notify
  after insert or update of assigned_to on leads
  for each row execute function notify_lead_assigned();

-- A task finished or a lead won or lost, told to the owner and the office.
-- Every status change goes through change_log, from the website and from
-- WhatsApp alike, so this is the one place that sees all of them - and it
-- knows who did it, so nobody is told about their own change.
create function notify_status_change() returns trigger language plpgsql as $$
declare
  who text;
  what text;
  link text;
begin
  if new.field <> 'status' or new.kind not in ('task', 'lead') then
    return new;
  end if;
  select canonical_name into who from entities where id = new.changed_by;

  if new.kind = 'task' then
    select case new.after #>> '{}' when 'done' then 'finished: ' else 'reopened: ' end
             || left(t.description, 160),
           '/tasks/' || t.id
      into what, link
      from tasks t where t.id = new.item_id;
  else
    select 'marked ' || e.canonical_name || ' as ' || (new.after #>> '{}'),
           '/leads/' || l.id
      into what, link
      from leads l join entities e on e.id = l.entity_id where l.id = new.item_id;
  end if;
  if what is null then
    return new;
  end if;

  insert into notifications (recipient_id, kind, item_kind, item_id, body, url, actor_id)
  select u.entity_id, 'status', new.kind, new.item_id,
         coalesce(who, 'Someone') || ' ' || what, link, new.changed_by
  from app_users u
  where u.role in ('owner', 'office') and not u.disabled
    and u.entity_id is distinct from new.changed_by;
  return new;
end $$;

create trigger change_log_notify
  after insert on change_log
  for each row execute function notify_status_change();
