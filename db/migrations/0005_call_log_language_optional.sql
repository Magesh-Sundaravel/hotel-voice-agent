-- The call log row is written by the first tool call, before the caller's language
-- is always known (no ElevenLabs variable carries it). It is filled in later by a
-- tool that takes a language. The it/en check still applies to non-null values.
alter table call_log alter column language drop not null;
