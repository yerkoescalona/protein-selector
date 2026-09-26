"""Tests for protein_selector.domain.bioinformatics.ebi_hmmer.

The HTTP session is mocked with answers shaped like EBI's live HMMER API (submission,
polling, the ``fullfasta`` download that answers HTTP 500 while generating), verified
before they were written (PLAN.md §40), so nothing here touches the network.
"""

from __future__ import annotations

import gzip
from unittest.mock import MagicMock

import pytest
import requests

from protein_selector.domain.bioinformatics import ebi_hmmer as module
from protein_selector.domain.bioinformatics.ebi_hmmer import run_phmmer
from protein_selector.domain.bioinformatics.models import (
    PhmmerSearch,
    SequenceSearchError,
)


def _response(status=200, json_data=None, content=b"", json_error=False):
    response = MagicMock()
    response.status_code = status
    response.content = content
    if json_error:
        response.json.side_effect = ValueError("not JSON")
    else:
        response.json.return_value = json_data

    def raise_for_status():
        if status >= 400:
            raise requests.HTTPError(f"HTTP {status}")

    response.raise_for_status.side_effect = raise_for_status
    return response


def _success(nincluded):
    return _response(
        json_data={"status": "SUCCESS", "result": {"stats": {"nincluded": nincluded}}}
    )


_STARTED = {"status": "STARTED"}


class TestRunPhmmer:
    def test_submit_poll_then_download_full_lengths_after_a_500(self):
        fasta = ">FTSZ1_METJA\nACDEFG\n"
        session = MagicMock()
        session.post.side_effect = [
            _response(json_data={"id": "job-1"}),  # submit
            _response(status=204),  # ask the server to generate the file
        ]
        session.get.side_effect = [
            _response(json_data=_STARTED),
            _success(1),
            _response(status=500),  # still generating
            _response(content=gzip.compress(fasta.encode())),
        ]

        search = run_phmmer("acd efg", "swissprot", session=session, poll_interval_seconds=0)

        assert search == PhmmerSearch(job_id="job-1", n_hits=1, full_fasta=fasta)
        submit_url = session.post.call_args_list[0].args[0]
        body = session.post.call_args_list[0].kwargs["json"]
        assert submit_url.endswith("/search/phmmer")
        assert body == {
            "input": ">query\nACDEFG", "database": "swissprot", "incE": 0.01, "incdomE": 0.03,
        }
        assert session.post.call_args_list[1].args[0].endswith("/download/job-1/fullfasta")
        assert session.get.call_args_list[-1].args[0].endswith("/download/job-1/fullfasta")
        assert all(c.kwargs.get("timeout") for c in session.get.call_args_list)

    def test_an_uncompressed_body_is_read_as_text(self):
        session = MagicMock()
        session.post.side_effect = [_response(json_data={"id": "j"}), _response(status=204)]
        session.get.side_effect = [_success(1), _response(content=b">A_X\nAC\n")]
        search = run_phmmer("AC", "swissprot", session=session, poll_interval_seconds=0)
        assert search.full_fasta == ">A_X\nAC\n"

    @pytest.mark.parametrize(
        "damage",
        [
            lambda body: body[: len(body) // 2],  # truncated: EOFError
            lambda body: body[:-8] + b"\x00" * 8,  # bad CRC trailer: BadGzipFile
            lambda body: body[:10] + b"\xff" * (len(body) - 10),  # corrupt stream: zlib.error
        ],
        ids=["truncated", "bad-trailer", "corrupt-stream"],
    )
    def test_a_damaged_gzip_body_is_a_search_error(self, damage):
        body = gzip.compress(b">FTSZ1_METJA\nACDEFG\n" * 50)
        session = MagicMock()
        session.post.side_effect = [_response(json_data={"id": "j"}), _response(status=204)]
        session.get.side_effect = [_success(1), _response(content=damage(body))]
        with pytest.raises(SequenceSearchError, match="not valid gzip"):
            run_phmmer("ACDEFG", "swissprot", session=session, poll_interval_seconds=0)

    def test_zero_hits_never_asks_for_the_sequences(self):
        session = MagicMock()
        session.post.return_value = _response(json_data={"id": "job-0"})
        session.get.side_effect = [_success(0)]

        search = run_phmmer("ACDEFG", "swissprot", session=session, poll_interval_seconds=0)

        assert search == PhmmerSearch(job_id="job-0", n_hits=0, full_fasta=None)
        assert session.post.call_count == 1
        assert session.get.call_count == 1

    def test_a_transient_5xx_or_non_json_page_while_polling_is_asked_again(self):
        session = MagicMock()
        session.post.return_value = _response(json_data={"id": "j"})
        session.get.side_effect = [
            _response(status=502),
            _response(json_error=True),
            _success(0),
        ]
        assert run_phmmer("AC", "swissprot", session=session, poll_interval_seconds=0).n_hits == 0

    def test_a_search_that_never_finishes_times_out(self):
        session = MagicMock()
        session.post.return_value = _response(json_data={"id": "stuck"})
        session.get.return_value = _response(json_data=_STARTED)
        with pytest.raises(TimeoutError, match="stuck"):
            run_phmmer("AC", "swissprot", session=session, deadline_seconds=0, poll_interval_seconds=0)

    def test_sequences_that_never_appear_time_out(self):
        session = MagicMock()
        session.post.side_effect = [_response(json_data={"id": "j"}), _response(status=204)]
        session.get.side_effect = [_success(3)] + [_response(status=500)] * 5
        with pytest.raises(TimeoutError, match="full-length"):
            run_phmmer("AC", "swissprot", session=session, deadline_seconds=0, poll_interval_seconds=0)

    def test_the_wait_between_polls_grows_and_is_capped(self, monkeypatch):
        slept = []
        monkeypatch.setattr(module.time, "sleep", slept.append)
        session = MagicMock()
        session.post.return_value = _response(json_data={"id": "j"})
        session.get.side_effect = [_response(json_data=_STARTED)] * 8 + [_success(0)]
        run_phmmer("AC", "swissprot", session=session, poll_interval_seconds=4)
        assert slept[0] == 4
        assert slept == sorted(slept)
        assert max(slept) == 10

    def test_a_request_timeout_propagates(self):
        session = MagicMock()
        session.post.side_effect = requests.Timeout("read timed out")
        with pytest.raises(requests.Timeout):
            run_phmmer("AC", "swissprot", session=session)

    def test_a_failed_job_raises(self):
        session = MagicMock()
        session.post.return_value = _response(json_data={"id": "j"})
        session.get.return_value = _response(json_data={"status": "FAILURE"})
        with pytest.raises(SequenceSearchError, match="FAILURE"):
            run_phmmer("AC", "swissprot", session=session, poll_interval_seconds=0)

    def test_an_unknown_job_is_an_http_error(self):
        session = MagicMock()
        session.post.return_value = _response(json_data={"id": "gone"})
        session.get.return_value = _response(status=404)
        with pytest.raises(requests.HTTPError):
            run_phmmer("AC", "swissprot", session=session, poll_interval_seconds=0)

    def test_an_invalid_sequence_is_rejected_at_submission(self):
        session = MagicMock()
        session.post.return_value = _response(status=422)
        with pytest.raises(requests.HTTPError):
            run_phmmer("!!", "swissprot", session=session)
