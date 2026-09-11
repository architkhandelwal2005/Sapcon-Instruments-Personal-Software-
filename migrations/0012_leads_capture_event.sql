-- entities.capture_event_id (0011) only gets set when a capture actually CREATES a
-- new entity - when an item resolves to an existing entity (already known from a
-- meeting, or from an earlier photo), that entity's origin is untouched, so the new
-- capture_event has no way to find what it touched. leads.capture_event_id is the
-- reliable link: every capture item that resolves to anything always creates one
-- lead row, whether the entity was new or linked - the review screen finds a
-- capture's items through its leads, not through entity origin.

alter table leads add column capture_event_id uuid references capture_events(id);
create index leads_capture_event_idx on leads (capture_event_id);
