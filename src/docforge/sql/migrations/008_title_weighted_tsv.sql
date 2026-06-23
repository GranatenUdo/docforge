-- Migration 008: weighted text_tsv with title and section_title.
--
-- Replaces migration 007's plain to_tsvector('english', text) with a
-- three-tier weighted variant: title='A', section_title='B', text='D'.
-- ts_rank_cd respects setweight using its default weights array
-- {A: 1.0, B: 0.4, C: 0.2, D: 0.1}, so title tokens contribute ~10x a
-- body token in Postgres ts_rank_cd (cover-density) ranking.
--
-- Postgres GENERATED ALWAYS expressions cannot be modified in place;
-- the column is dropped and re-created. Lock window is roughly 15-90s
-- on ~20k chunks (mostly the ADD COLUMN ... STORED step recomputing
-- three to_tsvector calls per row under AccessExclusiveLock). Acceptable
-- for low-volume production; revisit if corpus grows past ~1M chunks.
--
-- Idempotency: best-effort via IF [NOT] EXISTS qualifiers. Re-running
-- causes an unnecessary drop+recreate of text_tsv but doesn't break
-- anything. The migration runs once per release in practice.

-- Step 1: add the title column (idempotent).
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT '';

-- Step 2: backfill title from sources via JOIN UPDATE.
-- Only updates rows where title is still the empty default — protects
-- against repeat runs that would otherwise rewrite the same data.
UPDATE chunks
SET title = s.title
FROM sources s
WHERE s.id = chunks.source_id AND chunks.title = '';

-- Step 3: drop the v0.5.0 text_tsv (plain to_tsvector('english', text)).
ALTER TABLE chunks DROP COLUMN IF EXISTS text_tsv;

-- Step 4: re-add text_tsv with the three-tier weighted expression.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS text_tsv tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', title), 'A') ||
        setweight(to_tsvector('english', coalesce(section_title, '')), 'B') ||
        setweight(to_tsvector('english', text), 'D')
    ) STORED;

-- Step 5: re-create the GIN index (was dropped with the old column).
CREATE INDEX IF NOT EXISTS chunks_text_tsv_idx ON chunks USING GIN (text_tsv);
