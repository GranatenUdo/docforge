CREATE TABLE IF NOT EXISTS query_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_name TEXT NOT NULL,
    team_name TEXT NOT NULL,
    area_name TEXT,
    query TEXT NOT NULL,
    result_count INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS query_log_created_at_idx ON query_log (created_at);
