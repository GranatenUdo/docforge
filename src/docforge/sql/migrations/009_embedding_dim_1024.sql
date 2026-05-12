-- Migration 009: switch embedding dim 768 -> 1024 for Qwen-4B (via MRL).
--
-- BREAKING: this migration drops and recreates the embedding column.
-- Existing 768-dim vectors are lost. Re-ingest is required.
-- Run only during a scheduled maintenance window.
--
-- Order: drop the HNSW index before ALTER COLUMN (Postgres may refuse
-- to ALTER a column that's part of an index). The index is recreated
-- on the new column at the end.

DROP INDEX IF EXISTS chunks_embedding_idx;

ALTER TABLE chunks DROP COLUMN IF EXISTS embedding;

ALTER TABLE chunks ADD COLUMN embedding vector(1024);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks
    USING hnsw (embedding vector_cosine_ops);
