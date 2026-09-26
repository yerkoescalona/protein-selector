"""phmmer on EBI's HMMER web API, and the full-length sequences of its significant hits.

Adapter for one external service (PLAN.md §34c, §40). ``run_phmmer`` submits a sequence
(``POST /search/phmmer``, both inclusion thresholds pinned), polls ``GET /result/{id}``
until ``SUCCESS`` and reads ``stats.nincluded``, the significant hits. Only when that is
positive does it ask for their **full-length** sequences (``POST`` then ``GET
/download/{id}/fullfasta``), which the server answers with HTTP 500 while generating and
HTTP 200 with gzip bytes once ready. The file lists the hits in rank order, best first.
One deadline bounds the whole search, so a stuck job raises ``TimeoutError`` instead of
hanging a worker.
"""

from __future__ import annotations

import gzip
import time
import zlib

import requests

from protein_selector.domain.bioinformatics.models import (
    PhmmerSearch,
    SequenceSearchError,
    clean_sequence,
)

HMMER_API_URL = "https://www.ebi.ac.uk/Tools/hmmer/api/v1"

# Both inclusion thresholds are pinned so "significant" cannot drift with a server default.
# The values are the EBI server's own defaults (its OpenAPI SearchRequestSchema): a hit is
# included at a full-sequence E-value of 0.01 or better, a domain at a conditional E-value
# of 0.03 or better.
_INCLUSION_EVALUE = 0.01
_DOMAIN_INCLUSION_EVALUE = 0.03

_REQUEST_TIMEOUT_SECONDS = 60
# Usually 2-8 s, but one Swiss-Prot job took 257 s end to end (PLAN.md §40).
_SEARCH_DEADLINE_SECONDS = 600
_POLL_INTERVAL_SECONDS = 1.0
_MAX_POLL_INTERVAL_SECONDS = 10.0

_SUCCESS = "SUCCESS"
_FAILED_STATUSES = frozenset({"FAILURE", "ERROR", "REVOKED"})
_GZIP_MAGIC = b"\x1f\x8b"


def run_phmmer(
    sequence: str,
    database: str,
    *,
    session: requests.Session | None = None,
    deadline_seconds: float = _SEARCH_DEADLINE_SECONDS,
    poll_interval_seconds: float = _POLL_INTERVAL_SECONDS,
) -> PhmmerSearch:
    """Search ``sequence`` against ``database``; fetch the significant hits in full.

    Transport failures and 4xx answers raise ``requests.RequestException``; a search the
    server reports as failed, or an answer that cannot be read (a body that is not the
    JSON or gzip it should be), raises ``SequenceSearchError``; running past
    ``deadline_seconds`` raises ``TimeoutError``. A 5xx or non-JSON answer while polling,
    and HTTP 500 while the sequence file is being generated, mean "ask again"; the wait
    between asks grows from ``poll_interval_seconds`` to at most 10 s.
    ``find_sequence_relatives`` folds all of these into ``SequenceSearchError``.
    """
    http = session or requests
    deadline = time.monotonic() + deadline_seconds

    submitted = http.post(
        f"{HMMER_API_URL}/search/phmmer",
        json={
            "input": f">query\n{clean_sequence(sequence)}",
            "database": database,
            "incE": _INCLUSION_EVALUE,
            "incdomE": _DOMAIN_INCLUSION_EVALUE,
        },
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    submitted.raise_for_status()
    payload = submitted.json()
    job_id = payload.get("id") if isinstance(payload, dict) else None
    if not job_id:
        raise SequenceSearchError("phmmer submission returned no job id")

    waiter = _Waiter(deadline, poll_interval_seconds)
    stats = _poll_result(http, job_id, waiter)
    n_hits = stats.get("nincluded")
    if not isinstance(n_hits, int):
        raise SequenceSearchError(f"phmmer job {job_id} reported no nincluded count")
    if n_hits == 0:
        return PhmmerSearch(job_id=job_id, n_hits=0)
    full = _download_full_fasta(http, job_id, _Waiter(deadline, poll_interval_seconds))
    return PhmmerSearch(job_id=job_id, n_hits=n_hits, full_fasta=full)


class _Waiter:
    """Sleeps between polls, a little longer each time, until a shared deadline."""

    def __init__(self, deadline: float, interval: float) -> None:
        self.deadline = deadline
        self.interval = interval

    def wait(self, what: str) -> None:
        if time.monotonic() + self.interval > self.deadline:
            raise TimeoutError(f"{what} not ready before the deadline")
        time.sleep(self.interval)
        self.interval = min(self.interval * 1.5, _MAX_POLL_INTERVAL_SECONDS)


def _poll_result(http, job_id: str, waiter: _Waiter) -> dict:
    """Poll until the job succeeds; returns its ``result.stats``."""
    while True:
        response = http.get(
            f"{HMMER_API_URL}/result/{job_id}",
            params={"page_size": 1},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code < 500:
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                status = payload.get("status")
                if status == _SUCCESS:
                    result = payload.get("result")
                    stats = result.get("stats") if isinstance(result, dict) else None
                    return stats if isinstance(stats, dict) else {}
                if status in _FAILED_STATUSES:
                    raise SequenceSearchError(f"phmmer job {job_id} ended as {status}")
        waiter.wait(f"phmmer job {job_id}")


def _download_full_fasta(http, job_id: str, waiter: _Waiter) -> str:
    """Ask for the hits' full-length sequences, then fetch them once generated."""
    url = f"{HMMER_API_URL}/download/{job_id}/fullfasta"
    requested = http.post(url, timeout=_REQUEST_TIMEOUT_SECONDS)
    requested.raise_for_status()
    while True:
        response = http.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
        if response.status_code == 200:
            return _decode_body(response.content, job_id)
        if response.status_code < 500:
            response.raise_for_status()
        waiter.wait(f"full-length sequences for job {job_id}")


def _decode_body(body: bytes, job_id: str) -> str:
    """The file's text, from gzip or plain bytes.

    A truncated or corrupted gzip body raises ``SequenceSearchError``, so it costs this
    one candidate a retry instead of escaping as an ``EOFError`` or ``zlib.error``.
    """
    if body[:2] == _GZIP_MAGIC:
        try:
            body = gzip.decompress(body)
        except (OSError, EOFError, zlib.error) as exc:
            raise SequenceSearchError(
                f"full-length sequences for job {job_id} are not valid gzip: {exc}"
            ) from exc
    return body.decode("ascii", errors="replace")
