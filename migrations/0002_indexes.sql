-- Trigram search support for entity resolution (step 3), plus FK indexes
-- for the graph traversal / degree queries (step 4) and lead-gating lookups
-- (step 7), which all join relations <-> entities <-> meetings repeatedly.

create extension if not exists pg_trgm;

create index entities_canonical_name_trgm_idx
  on entities using gin (canonical_name gin_trgm_ops);

create index relations_source_id_idx on relations (source_id);
create index relations_target_id_idx on relations (target_id);
create index relations_meeting_id_idx on relations (meeting_id);
create index relations_type_idx on relations (relation_type);

create index meetings_primary_contact_id_idx on meetings (primary_contact_id);

create index tasks_related_entity_id_idx on tasks (related_entity_id);
create index tasks_meeting_id_idx on tasks (meeting_id);
create index tasks_due_date_idx on tasks (due_date) where status = 'open';
