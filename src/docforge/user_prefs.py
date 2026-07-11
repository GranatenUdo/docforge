"""Per-user docforge preferences persisted on the user's machine.

Used by `serve --remote-api` to remember the team id a user gave via the
set_team MCP tool (and whether they asked never to be asked again). All I/O
is best-effort: loading never raises and saving returns False on failure —
identity handling must never break a search (same philosophy as query_log).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

PREFS_FILENAME = "prefs.json"


def _os_name() -> str:
    """Seam for tests: monkeypatching os.name directly makes pathlib try to
    instantiate the other platform's Path flavor and crash."""
    return os.name


class UserPrefs(BaseModel):
    """Schema of the on-disk prefs file. Unknown keys are ignored on load."""

    version: int = 1
    team: str = ""
    declined: bool = False  # user said "never ask again"
    nudge_count: int = 0  # lifetime ask-for-team nudges emitted
    updated_at: str = ""  # ISO 8601 UTC, informational only


def prefs_path() -> Path:
    """Per-user prefs file, per OS convention.

    Windows: %LOCALAPPDATA%\\docforge\\prefs.json (machine-local state), with
    APPDATA then the home directory as fallbacks — the dw-docforge plugin's
    .mcp.json passes LOCALAPPDATA/APPDATA/USERPROFILE through to the server
    process. POSIX: $XDG_CONFIG_HOME/docforge/prefs.json, else
    ~/.config/docforge/prefs.json.
    """
    if _os_name() == "nt":
        for env in ("LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(env, "").strip()
            if base:
                return Path(base) / "docforge" / PREFS_FILENAME
        return Path.home() / ".docforge" / PREFS_FILENAME
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / "docforge" / PREFS_FILENAME


def load_prefs(path: Path | None = None) -> UserPrefs:
    """Read prefs; on ANY failure (missing, corrupt, wrong types) return defaults."""
    try:
        p = path or prefs_path()
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return UserPrefs()
        return UserPrefs.model_validate(data)
    except (OSError, ValueError, ValidationError):
        return UserPrefs()


def save_prefs(prefs: UserPrefs, path: Path | None = None) -> bool:
    """Atomically write prefs (tmp file + os.replace). Returns False and logs
    on failure; never raises. Concurrent writers are last-writer-wins."""
    p = path or prefs_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        prefs.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        fd, tmp_name = tempfile.mkstemp(dir=p.parent, prefix=".prefs-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(prefs.model_dump_json(indent=2))
            os.replace(tmp_name, p)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return True
    except OSError as e:
        logger.warning("could not save user prefs to %s: %s", p, e)
        return False


def valid_team_ids() -> list[str]:
    """Deployment-supplied team vocabulary from DOCFORGE_TEAM_IDS (comma-
    separated). Empty when unset — which also disables the ask-for-team nudge,
    so removing the env var from a deployment is a fleet-wide kill switch."""
    raw = os.environ.get("DOCFORGE_TEAM_IDS", "")
    return [t.strip().lower() for t in raw.split(",") if t.strip()]
