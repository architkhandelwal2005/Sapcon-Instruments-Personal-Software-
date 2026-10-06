-- Which records a note actually named.
--
-- A meeting could be reached from a company three ways: the company was the
-- meeting's primary contact, a relation referenced it, or a task was tied to
-- it. A field visit produces all three. An internal meeting produces none of
-- them - it has no outside primary contact, its connections are between people
-- rather than companies, and its tasks are about work rather than accounts.
--
-- So a note saying "Indofil has a new project at Dahej and Saurabh is touring
-- there" resolved Indofil, matched it to the right record, enriched it - and
-- then dropped the association on the floor. Asking "what's happening at
-- Indofil" returned the contact card and nothing else, because nothing in the
-- database said that note was about Indofil. The sales head's own debriefs
-- from the office are mostly internal meetings, so this was most of what he
-- records.
--
-- The association already exists during ingestion. This is only where it gets
-- kept.

create table meeting_mentions (
  id bigserial primary key,
  meeting_id uuid not null references meetings(id) on delete cascade,
  entity_id uuid not null references entities(id) on delete cascade,
  created_at timestamptz not null default now()
);

create index meeting_mentions_meeting_idx on meeting_mentions (meeting_id);
create index meeting_mentions_entity_idx on meeting_mentions (entity_id);

-- Deliberately NOT unique on (meeting_id, entity_id).
--
-- Merging two records repoints every column that references entities with a
-- plain UPDATE, discovered from the schema. The two records being merged were
-- usually both named in the same note - that is normally what revealed the
-- duplicate in the first place - so a unique constraint would make that update
-- collide precisely when merging matters most, and merging is the one repair
-- that cannot be done any other way.
--
-- A duplicate row costs nothing here: every read asks whether a mention
-- exists, never how many there are.
