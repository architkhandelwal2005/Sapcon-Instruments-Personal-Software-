-- Employees are entities too (entity_type='employee') - assignment ("who this lead
-- is allotted to") and provenance ("who logged this interaction") then both point
-- at the same table everything else already uses, instead of a second identity
-- system. Real names arrive later; seeded as placeholders by scripts/seed_employees.py.

alter table meetings add column logged_by uuid references entities(id);
-- who recorded the interaction: the uncle, office boy, or a marketing employee.
-- null on existing rows - the concept didn't exist before this migration.

alter table tasks add constraint tasks_assigned_to_fkey
  foreign key (assigned_to) references entities(id);
-- was unconstrained since migration 0001 ("will reference a users table once
-- multi-user exists") - it exists now.

create table whatsapp_senders (
  id uuid primary key default gen_random_uuid(),
  phone text not null unique,          -- E.164, e.g. +91...; empty until real numbers known
  entity_id uuid not null references entities(id),
  role text not null,                  -- 'owner' | 'office' | 'employee' - label only, no branching on it yet
  created_at timestamptz default now()
);
