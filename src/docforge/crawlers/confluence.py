"""Confluence REST API v2 page crawler with retry logic for transient errors."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

TRANSIENT_STATUS_CODES = {429, 502, 503, 504}
MAX_RETRIES = 3
BACKOFF_BASE = 2.0


@dataclass
class CrawledPage:
    page_id: str
    title: str
    space_key: str
    html_content: str
    content_hash: str
    version: int
    url: str
    last_modified: datetime  # version.createdAt from the v2 API; falls back to now() if missing


def _apply_stale_prefix(
    title: str,
    last_modified: datetime,
    threshold_months: int | None,
) -> str:
    """Return title with '[STALE YYYY] ' prefix if last_modified is older than
    threshold_months. Pure function. ~30 days/month is fine for staleness."""
    if threshold_months is None:
        return title
    now = datetime.now(timezone.utc)
    if last_modified.tzinfo is None:
        last_modified = last_modified.replace(tzinfo=timezone.utc)
    threshold_days = threshold_months * 30
    if (now - last_modified).days > threshold_days:
        return f"[STALE {last_modified.year}] {title}"
    return title


async def crawl_page(
    page_id: str,
    *,
    base_url: str,
    email: str,
    api_token: str,
    stale_threshold_months: int | None = 36,
) -> CrawledPage:
    """Fetch a Confluence page via REST API v2 and return its content.

    When `stale_threshold_months` is not None and the page's version.createdAt
    is older than that many months, the returned title is prefixed with
    `[STALE YYYY] `. Pass `None` to disable the prefix.
    """
    api_url = f"{base_url}/wiki/api/v2/pages/{page_id}"
    params = {"body-format": "storage"}
    auth = httpx.BasicAuth(email, api_token)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await _request_with_retry(client, api_url, params=params, auth=auth)

    data = response.json()
    html_content = data.get("body", {}).get("storage", {}).get("value", "")
    title = data.get("title", "")
    version_block = data.get("version", {})
    version = version_block.get("number", 0)
    space_id = data.get("spaceId", "")

    # Confluence v2 API returns ISO 8601 (e.g. "2024-03-15T10:30:00.000Z"). Python 3.12+
    # datetime.fromisoformat accepts the Z suffix directly.
    last_modified_raw = version_block.get("createdAt")
    if last_modified_raw:
        try:
            last_modified = datetime.fromisoformat(last_modified_raw)
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
        except ValueError as e:
            logger.warning(
                "Could not parse version.createdAt=%r for page %s: %s; treating as now()",
                last_modified_raw,
                page_id,
                e,
            )
            last_modified = datetime.now(timezone.utc)
    else:
        logger.debug(
            "Confluence page %s response missing version.createdAt; treating as now()",
            page_id,
        )
        last_modified = datetime.now(timezone.utc)

    title = _apply_stale_prefix(title, last_modified, stale_threshold_months)

    content_hash = hashlib.sha256(html_content.encode()).hexdigest()
    page_url = f"{base_url}/wiki/spaces/{space_id}/pages/{page_id}"

    return CrawledPage(
        page_id=page_id,
        title=title,
        space_key=space_id,
        html_content=html_content,
        content_hash=content_hash,
        version=version,
        url=page_url,
        last_modified=last_modified,
    )


async def enumerate_tree_page_ids(
    root_page_id: str,
    *,
    base_url: str,
    email: str,
    api_token: str,
    stale_months: int | None = 24,
) -> list[str]:
    """Return the IDs of all CURRENT descendant pages of ``root_page_id``,
    filtered to those edited within the last ``stale_months`` months
    (``None`` = no staleness filter).

    Uses Confluence CQL search (``ancestor=<id> and type=page``). CQL returns
    the full tree depth (the v2 ``/descendants`` endpoint silently caps depth)
    and excludes archived pages by default. Paginates via ``_links.base`` +
    ``_links.next`` — the ``next`` URL omits the ``/wiki`` context path, so the
    base is prepended.
    """
    cql = f"ancestor={root_page_id} and type=page"
    if stale_months is not None:
        # CQL now() units are CASE-SENSITIVE: "M" = months, "m" = MINUTES.
        # A lowercase m here would silently match only the last N minutes.
        cql += f' and lastmodified >= now("-{stale_months}M")'

    base = base_url.rstrip("/")
    auth = httpx.BasicAuth(email, api_token)
    url = f"{base}/wiki/rest/api/content/search"
    params: dict | None = {"cql": cql, "limit": 250}
    ids: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            response = await _request_with_retry(client, url, params=params, auth=auth)
            data = response.json()
            ids.extend(item["id"] for item in data.get("results", []))
            links = data.get("_links", {})
            nxt = links.get("next")
            if not nxt:
                break
            link_base = links.get("base") or f"{base}/wiki"
            url = nxt if nxt.startswith("http") else f"{link_base}{nxt}"
            params = None  # the next URL already encodes cql + cursor
    return ids


async def _request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    auth: httpx.BasicAuth | None = None,
) -> httpx.Response:
    """Make an HTTP GET request with retry logic for transient failures."""
    import asyncio

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.get(url, params=params, auth=auth)

            if response.status_code == 200:
                return response

            if response.status_code in TRANSIENT_STATUS_CODES:
                retry_after = float(response.headers.get("Retry-After", BACKOFF_BASE**attempt))
                logger.warning(
                    "Transient error %d for %s, retrying in %.1fs (attempt %d/%d)",
                    response.status_code,
                    url,
                    retry_after,
                    attempt + 1,
                    MAX_RETRIES,
                )
                await asyncio.sleep(retry_after)
                continue

            # Permanent failure
            response.raise_for_status()

        except httpx.TimeoutException:
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE**attempt
                logger.warning("Timeout for %s, retrying in %.1fs", url, wait)
                await asyncio.sleep(wait)
                continue
            raise

    raise httpx.HTTPStatusError(
        f"Max retries exceeded for {url}",
        request=httpx.Request("GET", url),
        response=response,  # type: ignore[possibly-undefined]
    )
