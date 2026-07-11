"""MCP server that proxies tool calls to a remote docforge search-api.

Used by `docforge serve --remote-api $URL --auth ...`. See the
2026-05-08-docforge-remote-api-mode-design.md spec for the full design.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Protocol

import httpx
from fastmcp import FastMCP

from docforge import user_prefs
from docforge.formatters import format_search_results_markdown

logger = logging.getLogger(__name__)


class AuthName(str, Enum):
    """Selectable auth providers for the --remote-api mode."""

    none = "none"
    bearer = "bearer"
    azure = "azure"


class AuthProvider(Protocol):
    """Async source of HTTP headers attached to each remote request."""

    async def headers(self) -> dict[str, str]: ...


class NoneAuth:
    """No-op auth provider. Returns no headers."""

    async def headers(self) -> dict[str, str]:
        return {}


class BearerAuth:
    """Static Bearer token from DOCFORGE_API_TOKEN env var."""

    def __init__(self) -> None:
        token = os.environ.get("DOCFORGE_API_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BearerAuth requires DOCFORGE_API_TOKEN env var to be set.")
        self._token = token

    async def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}


class AzureAuth:
    """Entra Bearer token via DefaultAzureCredential.

    Requires `pip install docforge-cli[azure]`. Reads target audience
    from DOCFORGE_AUDIENCE env var.
    """

    def __init__(self) -> None:
        try:
            from azure.identity.aio import DefaultAzureCredential
        except ImportError as e:
            raise ImportError("Azure auth requires `pip install docforge-cli[azure]`.") from e

        audience = os.environ.get("DOCFORGE_AUDIENCE", "").strip()
        if not audience:
            raise RuntimeError("AzureAuth requires DOCFORGE_AUDIENCE env var to be set.")
        self._audience = audience
        self._credential = DefaultAzureCredential()

    async def headers(self) -> dict[str, str]:
        # DefaultAzureCredential walks several credential providers (env,
        # managed identity, CLI, VS Code, etc.); if any one stalls — e.g.,
        # a corrupted CLI token cache or a network glitch during MSAL
        # discovery — the get_token coroutine can hang indefinitely. 15s
        # is well past the cold-network worst case (~3s for CLI cache load)
        # but short enough that the user sees a clear error instead of
        # an apparently-hung MCP session.
        t0 = time.perf_counter()
        logger.info("auth requesting token")
        try:
            token = await asyncio.wait_for(
                self._credential.get_token(f"{self._audience}/.default"),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            logger.warning("auth TIMEOUT after %dms", int((time.perf_counter() - t0) * 1000))
            raise
        except Exception as e:
            logger.warning(
                "auth FAILED after %dms: %s",
                int((time.perf_counter() - t0) * 1000),
                type(e).__name__,
            )
            raise
        logger.info("auth token acquired in %dms", int((time.perf_counter() - t0) * 1000))
        return {"Authorization": f"Bearer {token.token}"}


class _StartupFailedAuth:
    """Substitute auth provider used when the real provider can't be constructed
    (missing `[azure]` extra, unset DOCFORGE_AUDIENCE/DOCFORGE_API_TOKEN, etc.).

    Lets `serve --remote-api` finish the MCP `initialize` handshake so `/mcp`
    shows the server as connected instead of dying with an opaque -32000 process
    crash. The real, actionable error is surfaced as a tool RESULT on the first
    search/list call: RemoteBackend._request awaits headers(), catches the
    exception, and returns it as `"Auth provider error: …"`.
    """

    def __init__(self, auth_name: object, error: Exception) -> None:
        self._message = (
            f"docforge could not initialize '{auth_name}' authentication: {error} "
            "Fix the above, then restart Claude Code (or run /mcp -> Reconnect)."
        )

    async def headers(self) -> dict[str, str]:
        raise RuntimeError(self._message)


def make_auth_provider(name: AuthName | str) -> AuthProvider:
    """Return an AuthProvider instance for the given name."""
    try:
        name = AuthName(name) if isinstance(name, str) else name
    except ValueError as e:
        raise ValueError(f"Unknown auth provider: {name!r}. Valid: none, bearer, azure.") from e
    if name is AuthName.none:
        return NoneAuth()
    if name is AuthName.bearer:
        return BearerAuth()
    if name is AuthName.azure:
        return AzureAuth()
    raise ValueError(f"Unknown auth provider: {name!r}.")


# Read timeout (seconds) for remote /search calls. Long enough to cover an
# Azure Container Apps cold start (~22s observed); short enough that a stuck
# upstream surfaces a clear error instead of hanging the MCP session.
_READ_TIMEOUT_S = 30.0


class RemoteBackend:
    """Proxy to a remote docforge search-api over HTTP."""

    def __init__(
        self,
        *,
        url: str,
        auth: AuthProvider,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._auth = auth
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        # Team resolved via set_team when the prefs file could not be written —
        # keeps the user's answer effective for the rest of this session.
        self.session_team: str = ""
        self._nudged = False  # ask-for-team nudge emitted in this process

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # Split timeouts let a connect stall (DNS, TCP, TLS) fail at 10s
            # without consuming the 30s read budget — needed because Azure
            # Container Apps cold-start can take ~22s of read time once
            # connected. Without this split, a hung connect would burn the
            # entire 30s window before the user sees an error.
            self._client = httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(connect=10.0, read=_READ_TIMEOUT_S, write=10.0, pool=5.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _identity_body(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for env_var, body_key in (
            ("DOCFORGE_USER", "user_name"),
            ("DOCFORGE_TEAM", "team_name"),
            ("DOCFORGE_AREA", "area_name"),
        ):
            val = os.environ.get(env_var, "").strip()
            # "${" guards against unsubstituted client templates (e.g. a
            # literal "${user_config.team}" leaking through the plugin env).
            if val and "${" not in val:
                out[body_key] = val
        if "team_name" not in out:
            # env > persisted prefs > session memory (set_team with failed save).
            # Read fresh per search so a set_team from a parallel session is
            # picked up without a restart. Never let prefs I/O break a search.
            try:
                team = user_prefs.load_prefs().team.strip()
            except Exception:  # noqa: BLE001 — C2: identity must never break search
                team = ""
            if team and ("${" in team or not _TEAM_ID_RE.match(team)):
                # Hand-edited/corrupt prefs bypass set_team's write-side
                # validation; fail safe to "no team" rather than send junk.
                team = ""
            team = team or self.session_team
            if team:
                out["team_name"] = team
        return out

    def _maybe_team_nudge(self) -> str:
        """One-time "ask the user for their team" note, appended after
        successful search results. Gated on the deployment opting in via
        DOCFORGE_TEAM_IDS — generic deployments never see it. Never raises.
        Does blocking prefs I/O: callers must run it via asyncio.to_thread."""
        try:
            if self._nudged:
                return ""
            ids = user_prefs.valid_team_ids()
            if not ids:
                return ""
            prefs = user_prefs.load_prefs()
            if prefs.team.strip() or self.session_team:
                # A team got resolved after the identity snapshot (parallel
                # session or tool call, or a transient prefs-read failure in
                # _identity_body) — never ask for what is already answered.
                return ""
            if prefs.declined or prefs.nudge_count >= _NUDGE_LIFETIME_CAP:
                self._nudged = True  # nothing can un-gate this process; stop re-reading
                return ""
            self._nudged = True
            prefs.nudge_count += 1
            # Whole-file last-writer-wins: the team=="" check above narrows the
            # window in which this save could clobber a concurrent set_team to
            # the few ms between load and replace.
            user_prefs.save_prefs(prefs)  # best-effort; cap degrades to per-session
            return TEAM_NUDGE_TEMPLATE.format(ids=", ".join(ids), first_two_ids=", ".join(ids[:2]))
        except Exception as e:  # noqa: BLE001 — C2: nudge must never break search
            logger.warning("team nudge skipped: %s", e)
            return ""

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
    ) -> httpx.Response | str:
        """Perform an HTTP request with auth and uniform error handling.

        Retries once on 5xx with a 2-second backoff — cold-start 502/503 from
        Azure Container Apps ingress is the dominant transient failure. 4xx
        responses and timeouts are NOT retried: 4xx is caller-fault, and a
        timeout has already burned the configured budget.

        Returns the Response on 2xx; an already-formatted error string otherwise.
        """
        try:
            headers = await self._auth.headers()
        except Exception as e:
            return f"Auth provider error: {e}"

        client = await self._ensure_client()

        async def _attempt() -> httpx.Response | str:
            t0 = time.perf_counter()
            logger.info("request %s %s start", method, path)
            try:
                resp = await client.request(
                    method, f"{self._url}{path}", json=json, headers=headers
                )
            except httpx.ConnectError:
                logger.warning(
                    "request %s %s CONNECT_ERROR after %dms",
                    method,
                    path,
                    int((time.perf_counter() - t0) * 1000),
                )
                return f"Could not reach remote API at {self._url}."
            except httpx.ReadTimeout:
                logger.warning(
                    "request %s %s READ_TIMEOUT after %dms",
                    method,
                    path,
                    int((time.perf_counter() - t0) * 1000),
                )
                return (
                    f"DocForge /search timed out after {int(_READ_TIMEOUT_S)}s "
                    f"(Container App may be cold-starting; retry in 30s)."
                )
            except httpx.HTTPError as e:
                logger.warning(
                    "request %s %s HTTP_ERROR after %dms: %s",
                    method,
                    path,
                    int((time.perf_counter() - t0) * 1000),
                    type(e).__name__,
                )
                return f"Remote API error: {e}"

            logger.info(
                "request %s %s -> %d in %dms",
                method,
                path,
                resp.status_code,
                int((time.perf_counter() - t0) * 1000),
            )
            if resp.status_code == 401:
                return "Auth failed (401). Check DOCFORGE_API_URL and the --auth provider."
            if 500 <= resp.status_code < 600:
                return resp  # caller decides: retry or surface
            if resp.status_code != 200:
                return f"Remote API returned {resp.status_code}: {resp.text[:200]}"
            return resp

        first = await _attempt()
        if isinstance(first, httpx.Response) and first.status_code == 200:
            return first
        if isinstance(first, httpx.Response) and 500 <= first.status_code < 600:
            # 5xx: backoff briefly, then retry once
            await asyncio.sleep(2.0)
            second = await _attempt()
            if isinstance(second, httpx.Response) and second.status_code == 200:
                return second
            if isinstance(second, httpx.Response):
                return f"Remote API error ({second.status_code}). Try again in a moment."
            return second  # already-formatted error string
        # _attempt only returns Response for 200 or 5xx; both handled above.
        # Anything else is already a formatted error string.
        return first

    async def search(self, *, query: str, limit: int = 10) -> str:
        """Search the remote API and return Markdown-formatted results."""
        body: dict[str, object] = {"query": query, "limit": limit}
        # to_thread: prefs-file reads can stall on network home dirs; blocking
        # the loop thread would also defeat the 60s safety-net timeout (its
        # cancellation is a loop callback and can't fire while the loop is
        # stuck in a syscall).
        identity = await asyncio.to_thread(self._identity_body)
        body.update(identity)
        logger.info("search: about to call _request")
        result = await self._request("POST", "/search", json=body)
        logger.info("search: _request returned (type=%s)", type(result).__name__)
        if isinstance(result, str):
            return result

        data = result.json()
        results = data.get("results", [])
        logger.info("search: JSON parsed (%d results), formatting", len(results))
        out = format_search_results_markdown(results)
        if "team_name" not in identity:
            nudge = await asyncio.to_thread(self._maybe_team_nudge)
            if nudge:
                out = f"{out}\n\n{nudge}"
        logger.info("search: formatted markdown (%d chars), returning", len(out))
        return out

    async def list_sources(self) -> str:
        """List indexed sources from the remote API."""
        result = await self._request("GET", "/sources")
        if isinstance(result, str):
            return result

        data = result.json()
        sources = data.get("sources", [])
        if not sources:
            return "No sources indexed."

        lines = [f"**{data.get('count', len(sources))} indexed sources:**\n"]
        for s in sources:
            lines.append(f"- **{s['title']}** ({s['chunk_count']} chunks, {s['status']})")
        return "\n".join(lines)


INSTRUCTIONS = (
    "Search across your team's indexed documentation including team responsibilities, "
    "coding guidelines, architecture standards, and cross-team interfaces. "
    "Use the search_documentation tool when you need information about other teams, "
    "shared coding practices, or organizational knowledge."
)
DEFAULT_TOOL_DESCRIPTION = (
    "Search across indexed documentation from Confluence pages and git repos."
)

# Lifetime cap on ask-for-team nudges. After this many emissions without an
# answer, repeated silence is treated as an answer and the user is left alone
# (set_team and the plugin Configure screen remain available).
_NUDGE_LIFETIME_CAP = 3

TEAM_NUDGE_TEMPLATE = """---

[docforge — one-time note to the assistant; not part of the search results]
The user's documentation searches are not yet tagged with a team. The tag is \
optional: it slightly boosts ranking of their own team's docs and helps the \
docs maintainers see adoption. Search works fully without it.
After you have finished answering the user's current question, ask once, \
briefly, whether they want to set a team for documentation search. Suggested \
phrasing: "One-time setup question: want me to tag your documentation \
searches with your team? It slightly boosts your team's docs in results — \
say a team id (e.g. {first_two_ids}), say 'no' to never be asked again, or \
just ignore this."
Valid team ids: {ids}
- If the user names a team: call the set_team tool with that id.
- If the user explicitly declines (e.g. "no", "don't ask again"): call \
set_team with never_ask_again=true so they are never asked again.
- If the user ignores the question, is unsure, or wants to decide later: do \
nothing — they may be asked again in a later session (3 times at most, ever).
Never guess or infer the team yourself. Do not raise this again in this \
conversation, and never delay or withhold an answer because of it."""

SET_TEAM_DESCRIPTION = (
    "Save the user's team id for documentation search on this machine (persists "
    "across sessions). Only call this when the user has explicitly stated their "
    "team in this conversation, or with never_ask_again=true when the user has "
    "declined to set one — never guess or infer the team. Passing a valid team "
    "id replaces any previous value and clears a previous decline. Not needed "
    "if a team is already configured in the plugin settings."
)

# Free-form team ids (deployments without DOCFORGE_TEAM_IDS): conservative slug.
_TEAM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def apply_set_team(backend: RemoteBackend, team: str = "", never_ask_again: bool = False) -> str:
    """Validate + persist a set_team call. Pure-ish core of the MCP tool
    (module-level for direct unit testing). Returns a user-facing string;
    never raises. An explicit team wins over a simultaneous decline."""
    team = (team or "").strip().lower()
    ids = user_prefs.valid_team_ids()

    if not team and not never_ask_again:
        return "Nothing to do: pass team, or never_ask_again=true to stop the team question."

    if team:
        if ids and team not in ids:
            return (
                f"'{team}' is not a recognized team id. Valid ids: {', '.join(ids)}. "
                "Ask the user to pick one, or call set_team with never_ask_again=true "
                "if they would rather not set one."
            )
        if not ids and not _TEAM_ID_RE.match(team):
            return (
                f"'{team}' is not a valid team id (lowercase letters, digits, "
                "'.', '_', '-'; max 64 chars)."
            )
        backend.session_team = team
        backend._nudged = True  # the question is answered; suppress any in-flight nudge
        prefs = user_prefs.load_prefs()
        prefs.team = team
        prefs.declined = False
        if user_prefs.save_prefs(prefs):
            msg = (
                f"Team set to '{team}' (saved to {user_prefs.prefs_path()}). Future "
                "documentation searches from this machine will carry this team tag."
            )
        else:
            msg = (
                f"Could not save the team preference to disk; using '{team}' for "
                "this session only. To set it permanently, configure the team in "
                "the plugin's settings."
            )
        env_team = os.environ.get("DOCFORGE_TEAM", "").strip()
        if env_team and "${" not in env_team:
            msg += (
                f" Note: the plugin config currently sets team '{env_team}', which "
                "takes precedence over this saved value; update the plugin's team "
                "setting to change it."
            )
        return msg

    backend._nudged = True  # honor the decline for this session even if the save fails
    prefs = user_prefs.load_prefs()
    prefs.declined = True
    if user_prefs.save_prefs(prefs):
        return (
            "Understood — the team question will not be raised again on this "
            "machine. Searches are unaffected. If the user changes their mind "
            "later, call set_team with their team id."
        )
    return (
        "Understood — the team question will not be raised again in this session "
        "(the preference could not be saved to disk, so it may come up again in "
        "a future session). Searches are unaffected."
    )


# Hard outer bound on a single MCP tool call, in seconds. Sized to comfortably
# cover the worst inner budget — Azure token mint (15s) + first httpx read
# (30s) + retry backoff (2s) + second httpx read (30s) ≈ 77s but in practice
# only one of token / read can hit its full budget. 60s leaves headroom for
# scheduler slop while still guaranteeing the caller gets a clear error well
# inside any client-side MCP timeout. If any inner coro fails to honor
# cancellation (Azure SDK token refresh, FastMCP stdio, httpx pool), this
# outer asyncio.timeout still fires and returns a diagnostic string.
_TOOL_TIMEOUT_S = 60.0


async def _run_tool_with_timeout(name: str, coro_fn: Callable[[], Awaitable[str]]) -> str:
    """Wrap an MCP tool body in a hard outer timeout + log breadcrumbs.

    `coro_fn` is a no-arg callable that returns a fresh coroutine each call.
    We deliberately accept a factory (not an already-awaited coroutine) so
    `asyncio.timeout()` can cancel a freshly-started task — passing an
    already-created coroutine would mean we couldn't restart it on retry
    and could leak references on cancellation.

    On timeout the inner task is cancelled and we return a clear diagnostic
    string instead of raising, since FastMCP tool handlers are expected to
    return strings.
    """
    t0 = time.perf_counter()
    logger.info("tool=%s start", name)
    try:
        async with asyncio.timeout(_TOOL_TIMEOUT_S):
            result = await coro_fn()
        logger.info("tool=%s done in %dms", name, int((time.perf_counter() - t0) * 1000))
        return result
    except asyncio.TimeoutError:
        logger.warning(
            "tool=%s HIT SAFETY-NET TIMEOUT after %dms",
            name,
            int((time.perf_counter() - t0) * 1000),
        )
        return (
            f"docforge tool '{name}' hit the {int(_TOOL_TIMEOUT_S)}s safety-net timeout. "
            "An inner call hung without honoring cancellation. "
            "Check the MCP server stderr logs for the LAST PHASE REACHED. "
            "Common causes: Azure auth credential cache corruption, "
            "Container App cold start during 5xx retry, FastMCP stdio deadlock."
        )


def build_remote_mcp(
    *,
    url: str,
    auth_name: AuthName | str = AuthName.none,
    instructions: str | None = None,
    tool_description: str | None = None,
) -> FastMCP:
    """Construct (but do not run) the remote-backed MCP server.

    `instructions` and `tool_description` default to the engine's built-in
    generic text when None; deployments inject their own via Settings.
    Returned without running so the wiring is unit-testable."""
    try:
        auth = make_auth_provider(auth_name)
    except Exception as e:  # noqa: BLE001 — any construction failure must degrade
        # to a connected-but-degraded server, not a startup crash (-32000).
        logger.warning("auth provider %r could not be constructed: %s", auth_name, e)
        auth = _StartupFailedAuth(auth_name, e)
    backend = RemoteBackend(url=url, auth=auth)
    mcp = FastMCP("docforge", instructions=instructions or INSTRUCTIONS)

    @mcp.tool(description=tool_description or DEFAULT_TOOL_DESCRIPTION)
    async def search_documentation(query: str, limit: int = 10) -> str:
        return await _run_tool_with_timeout(
            "search_documentation",
            lambda: backend.search(query=query, limit=limit),
        )

    @mcp.tool()
    async def list_sources() -> str:
        """List all documentation sources currently indexed."""
        return await _run_tool_with_timeout(
            "list_sources",
            lambda: backend.list_sources(),
        )

    @mcp.tool(description=SET_TEAM_DESCRIPTION)
    async def set_team(team: str = "", never_ask_again: bool = False) -> str:
        # to_thread: prefs I/O can stall on network home dirs; keep the loop
        # free and let the safety-net timeout return a diagnostic.
        return await _run_tool_with_timeout(
            "set_team",
            lambda: asyncio.to_thread(apply_set_team, backend, team, never_ask_again),
        )

    return mcp


def run_remote_mcp(
    *,
    url: str,
    auth_name: AuthName | str = AuthName.none,
    instructions: str | None = None,
    tool_description: str | None = None,
) -> None:
    """Run an MCP server proxying tool calls to a remote docforge search-api."""
    try:
        mcp = build_remote_mcp(
            url=url,
            auth_name=auth_name,
            instructions=instructions,
            tool_description=tool_description,
        )
    except Exception as e:  # noqa: BLE001 — surface a clear diagnostic, then re-raise
        print(
            f"docforge serve failed to start: {type(e).__name__}: {e}\n"
            "This usually means a bad docforge.yml/.env or a packaging problem. "
            "Verify `docforge --version`, then reinstall: "
            'pip install --upgrade "docforge-cli[azure]".',
            file=sys.stderr,
        )
        raise
    mcp.run()
