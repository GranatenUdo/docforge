ALTER TABLE query_log ADD COLUMN IF NOT EXISTS user_oid TEXT;
CREATE INDEX IF NOT EXISTS query_log_user_oid_idx ON query_log (user_oid);
