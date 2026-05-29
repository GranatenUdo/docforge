-- Per-result capture for the /search response. Snapshots only (chunk/source IDs
-- are unstable across re-ingest and aren't projected by the /search SELECT).
-- Cascades with query_log so it inherits the 180-day retention cleanup.
CREATE TABLE IF NOT EXISTS query_result (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_log_id  UUID NOT NULL REFERENCES query_log(id) ON DELETE CASCADE,
    rank          INT NOT NULL,
    score         DOUBLE PRECISION NOT NULL,
    source_url    TEXT NOT NULL,
    source_title  TEXT NOT NULL,
    section_title TEXT,
    chunk_text    TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS query_result_query_log_id_idx ON query_result (query_log_id);
