"""Confluence REST API v2 page crawler with retry logic for transient errors."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

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


async def crawl_page(
    page_id: str,
    *,
    base_url: str,
    email: str,
    api_token: str,
) -> CrawledPage:
    """Fetch a Confluence page via REST API v2 and return its content."""
    api_url = f"{base_url}/wiki/api/v2/pages/{page_id}"
    params = {"body-format": "storage"}
    auth = httpx.BasicAuth(email, api_token)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await _request_with_retry(client, api_url, params=params, auth=auth)

    data = response.json()
    html_content = data.get("body", {}).get("storage", {}).get("value", "")
    title = data.get("title", "")
    version = data.get("version", {}).get("number", 0)
    space_id = data.get("spaceId", "")

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
    )


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
