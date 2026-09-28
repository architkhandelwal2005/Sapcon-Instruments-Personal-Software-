-- "undo" said on its own takes the most recent undoable change in the chat.
-- Nothing recorded that a token had already been spent, and nothing stopped one
-- from being reached weeks later - so "undo" typed out of context could silently
-- reverse a change nobody was thinking about. An undo is about the thing that
-- just happened; anything older is a job for the website, where you can see what
-- you are changing.
alter table whatsapp_pending add column used_at timestamptz;
