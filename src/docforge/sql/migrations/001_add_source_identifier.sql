ALTER TABLE sources ADD COLUMN IF NOT EXISTS source_identifier TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS sources_source_identifier_unique
    ON sources (source_identifier) WHERE source_identifier IS NOT NULL;
