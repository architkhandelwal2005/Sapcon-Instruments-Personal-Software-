-- Setup codes are gone. There was no channel to send one on, so the owner had
-- to read every code out loud and became the help desk for every new joiner.
-- An account is now claimed instead: the first sign-in on a number the owner
-- registered chooses that account's PIN, and the account refuses to be claimed
-- twice.
alter table app_users drop column if exists enrol_code_hash;
alter table app_users drop column if exists enrol_expires_at;
