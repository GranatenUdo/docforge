-- The remote-api MCP client omits team_name when the user has no team
-- configured, and /search accepts that (SearchRequest.team_name is optional) —
-- but this column's NOT NULL constraint then made log_search fail, and by
-- design it swallows the error: searches succeeded, telemetry rows silently
-- vanished (observed in prod, 2026-07). team_name is an optional client
-- routing hint — identity comes from the JWT — so NULL is the honest value.
-- Idempotent: DROP NOT NULL on an already-nullable column is a no-op.
ALTER TABLE query_log ALTER COLUMN team_name DROP NOT NULL;
