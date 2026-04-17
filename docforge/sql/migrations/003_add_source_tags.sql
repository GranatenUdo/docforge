ALTER TABLE sources
    ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS sources_tags_idx ON sources USING gin (tags);
