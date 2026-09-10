-- Contact fields, evidence-backed by the visit/expo list: 98% of ~700 real
-- records carry email, 95% carry phone, every person row carries a
-- title/department. These are core to a contact record ("who is this, how
-- do I reach them, where did I first meet them"), not speculative.
--
-- source: 'visit_list' | 'expo: <name>' | 'meeting' | null
--   marks how an entity entered the system - a seeded contact reads
--   differently from one first met on a recorded voice note.
-- first_seen: the visit/expo date. Real recorded meetings supersede this
--   as the interaction-history anchor once they exist.
alter table entities
  add column phone text,
  add column email text,
  add column title text,
  add column source text,
  add column first_seen date;
