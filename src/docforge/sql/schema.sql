CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    confluence_page_id TEXT,
    confluence_space_key TEXT,
    source_identifier TEXT,
    last_crawled_at TIMESTAMPTZ,
    content_hash TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT sources_confluence_page_id_unique UNIQUE (confluence_page_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    text TEXT NOT NULL,
    embedding vector(1024),
    section_title TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks
    USING hnsw (embedding vector_cosine_ops);
