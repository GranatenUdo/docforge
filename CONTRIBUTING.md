# Contributing to docforge

Thanks for your interest in contributing. This project is maintained by a single engineer at the time of writing; PRs are welcome but expect short feedback loops rather than fast review turnaround.

## Quickstart

```bash
git clone https://github.com/GranatenUdo/docforge
cd docforge
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate        # Linux / macOS
pip install -e ".[dev,entra]"
pytest -m "not integration"      # unit tests only; fast (<30s)
pytest -m integration            # integration tests; slower (~2min, spins up pgvector container)
```

For deeper architectural context, read `CLAUDE.md` at the repo root.

## PR requirements

Branch protection on `master` requires the two CI checks to pass before merge:

- **`lint`** — `ruff check docforge tests` + `ruff format --check docforge tests`
- **`test`** — `pytest -m "not integration"` with a ≥60% coverage gate

If you add a new Python file, running `pytest --cov` locally first avoids surprise CI failures.

### Migration files

SQL migrations live under `docforge/sql/migrations/` and are numbered sequentially: `NNN_description.sql`. The next free number is easy to see with `ls docforge/sql/migrations/ | tail -1`. Migrations are applied automatically by `docforge init-db` on fresh installs; existing deployments need the migration applied manually (see runbook).

### Schema changes to `query_log`

The `query_log` table is governed by `knowledge-hub/rag/docs/log-privacy.md`. Any change to its schema (new column, retention semantics, identity-handling) requires updating that doc in the same PR (or a follow-up PR merged before the schema change reaches production).

## Branch flow

- Branch per PR against `master`.
- Direct push to `master` is blocked by branch protection.
- Squash-merge is the default; feature-branch names follow `phase-N-spec-Y` or `feature/<short-name>`.

## Code style

- `ruff format` + `ruff check` are authoritative; CI rejects unformatted code.
- Python type hints on all function signatures.
- Pydantic v2 for data models; pydantic-settings for configuration.
- `async def` for endpoints and DB ops; sync is fine everywhere else.
- No type-checker in CI (deliberately — signal-over-ritual at solo-maintainer scale). Revisit if the team grows.

## Optional extras

- `docforge[dev]` — test + lint tooling.
- `docforge[entra]` — `fastapi-azure-auth` + `azure-identity` + `aiohttp`, required when `auth.mode: entra` in `docforge.yml`. For first-time Entra setup in a new tenant, see `deploy/azure/bootstrap-entra.sh` (one-shot script that creates the app registration, exposes the `search` scope, and grants tenant-wide consent).

## Where to ask

Open an issue at https://github.com/GranatenUdo/docforge/issues or email the maintainer (tobias.ens@docuware.com).
