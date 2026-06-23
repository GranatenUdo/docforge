"""The scaffold template's embedding dimension MUST match the schema's
vector(N) column — otherwise a fresh `docforge init` + `init-db` + `ingest`
fails at the pgvector insert. Regression guard for the 768-vs-1024 bug."""
import re
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1] / "src" / "docforge"


def _schema_vector_dim() -> int:
    schema = (PKG / "sql" / "schema.sql").read_text(encoding="utf-8")
    m = re.search(r"embedding\s+vector\((\d+)\)", schema)
    assert m, "could not find `embedding vector(N)` in schema.sql"
    return int(m.group(1))


def test_scaffold_dimensions_match_schema():
    tmpl = yaml.safe_load((PKG / "templates" / "docforge.yml").read_text(encoding="utf-8"))
    assert tmpl["embedding"]["dimensions"] == _schema_vector_dim()
