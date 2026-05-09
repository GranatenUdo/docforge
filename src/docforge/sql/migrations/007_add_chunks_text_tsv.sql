-- Migration 007: add tsvector column and GIN index for hybrid retrieval.
--
-- text_tsv is GENERATED ALWAYS AS STORED, so Postgres backfills existing
-- rows as part of the ALTER TABLE and auto-populates on every INSERT.
-- No application changes required for ingest.
--
-- The GIN index is built non-concurrently. For the current chunk count
-- (~tens of thousands) this is sub-second. If chunks grows past ~1M
-- rows, switch a future migration to CREATE INDEX CONCURRENTLY (which
-- requires running outside a transaction).

ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS text_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;

CREATE INDEX IF NOT EXISTS chunks_text_tsv_idx ON chunks USING GIN (text_tsv);
