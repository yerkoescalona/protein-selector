"""Literature-richness count via Europe PMC.

Per PLAN.md §3/§5, a plain, cheap integer count of articles citing a PDB structure --
one predicted-difficulty proxy, no LLM. Uses the documented ``ACCESSION_ID`` search field
plus ``ACCESSION_TYPE:pdb`` as a defense-in-depth namespace filter. No batch endpoint
exists (an OR'd multi-ID query returns a unioned count, not per-ID counts), so
``fetch_literature_counts`` makes one request per PDB ID, reusing one ``requests.Session``.

PLAN.md §27d S3.1: fanned out across a small bounded thread pool, throttled to a global
**8 requests/second** ceiling (a safety margin under Europe PMC's documented free-tier
10 req/s -- see A10, §27b) via ``_RateLimiter``, which serializes request *starts* across
every worker thread rather than just capping concurrency, so the 8 req/s bound holds
regardless of how many workers are in flight or how fast any one response comes back.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_REQUEST_TIMEOUT_SECONDS = 10
_MAX_REQUESTS_PER_SECOND = 8
_MAX_WORKERS = 8


class _RateLimiter:
    """Caps how often ``wait()`` returns across all calling threads combined.

    Not a per-thread limiter -- a shared lock means N threads calling
    ``wait()`` concurrently still can't exceed the combined rate, which a
    naive "each worker sleeps 1/rate between its own calls" scheme would
    allow (N workers would each independently run at ``rate``, for a
    combined N*rate).
    """

    def __init__(self, requests_per_second: float) -> None:
        self._min_interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start_at = max(now, self._next_allowed)
            self._next_allowed = start_at + self._min_interval
            sleep_for = start_at - now
        if sleep_for > 0:
            time.sleep(sleep_for)


def fetch_literature_count(
    pdb_id: str, session: requests.Session | None = None
) -> int | None:
    """Return the number of Europe PMC articles citing ``pdb_id``.

    Returns ``None`` (not ``0``) on any request failure or unexpected
    response shape -- "we don't know" is not the same as "zero papers cite
    this," matching this project's established unknown-vs-acceptable
    discipline (see ``simulability.py``).
    """
    http = session or requests
    query = f'ACCESSION_ID:"{pdb_id}" AND ACCESSION_TYPE:pdb'
    try:
        response = http.get(
            _SEARCH_URL,
            params={"query": query, "format": "json", "pageSize": 1},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    hit_count = payload.get("hitCount")
    return hit_count if isinstance(hit_count, int) else None


def fetch_literature_counts(pdb_ids: list[str]) -> dict[str, int | None]:
    """Fetch literature counts for a batch of PDB IDs, one request each.

    Reuses a single ``requests.Session`` across all calls for connection
    pooling -- the closest available approximation to "batched" for an API
    with no true batch endpoint. Requests fan out across a bounded thread
    pool (``_MAX_WORKERS``), throttled to ``_MAX_REQUESTS_PER_SECOND``
    combined -- see the module docstring and ``_RateLimiter``.
    """
    if not pdb_ids:
        return {}
    limiter = _RateLimiter(_MAX_REQUESTS_PER_SECOND)

    def _fetch_one(pdb_id: str, session: requests.Session) -> tuple[str, int | None]:
        limiter.wait()
        return pdb_id, fetch_literature_count(pdb_id, session=session)

    with requests.Session() as session, ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = [pool.submit(_fetch_one, pdb_id, session) for pdb_id in pdb_ids]
        return dict(future.result() for future in futures)
