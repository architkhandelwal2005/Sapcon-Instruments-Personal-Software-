-- Displayed fact only, never a routing/query input - the business routes
-- leads state-wise but that routing is entirely manual (single-user tool,
-- no accounts/roles for the ~50 team members). This just gives tomorrow's
-- state-organized ERP data somewhere to land. Nullable, no constraint: the
-- exact naming convention (state vs. custom territory) isn't known yet.
alter table entities add column region text;
