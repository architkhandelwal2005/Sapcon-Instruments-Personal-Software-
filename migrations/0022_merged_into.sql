-- Two records for one person could be flagged but never joined. The flag said
-- "these may be the same"; nothing could act on it, so "Mark Sapadia",
-- "Marmik Sapo Vadi" and "Marmik Sapovadia" accumulated as three people, and a
-- spelling correction sent on WhatsApp could only add a fourth.
--
-- A merged record is not deleted. Its rows move to the survivor and the row
-- itself stays, marked, pointing at where its history went - the same rule the
-- rest of the system follows for rejected items and dropped leads.
alter table entities add column merged_into uuid references entities(id);
create index entities_merged_idx on entities (merged_into) where merged_into is not null;
