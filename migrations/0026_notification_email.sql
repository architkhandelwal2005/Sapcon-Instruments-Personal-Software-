-- When a notification went out by email. Null means not yet; a notification
-- the person already read on the site is never emailed.
alter table notifications add column emailed_at timestamptz;
create index notifications_to_email_idx on notifications (created_at)
  where emailed_at is null and read_at is null;
