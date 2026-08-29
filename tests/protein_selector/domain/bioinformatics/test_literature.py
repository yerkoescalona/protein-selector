"""Tests for protein_selector.domain.bioinformatics.literature.

Network-touching calls (requests.get / requests.Session) are mocked -- see
.claude/CLAUDE.md "Testing" for the mocked-boundary rationale, and "Bugs
found via live verification" for why this doesn't replace live verification.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from protein_selector.domain.bioinformatics.literature import (
    fetch_literature_count,
    fetch_literature_counts,
)


def _mock_response(hit_count: int | None = 39, json_ok: bool = True) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    if json_ok:
        response.json.return_value = (
            {"hitCount": hit_count} if hit_count is not None else {}
        )
    else:
        response.json.side_effect = ValueError("not JSON")
    return response


class TestFetchLiteratureCount:
    def test_returns_hit_count_on_success(self):
        session = MagicMock()
        session.get.return_value = _mock_response(hit_count=39)

        assert fetch_literature_count("4HHB", session=session) == 39

    def test_query_uses_documented_accession_id_and_type_fields(self):
        session = MagicMock()
        session.get.return_value = _mock_response(hit_count=0)

        fetch_literature_count("4HHB", session=session)

        _, kwargs = session.get.call_args
        query = kwargs["params"]["query"]
        assert 'ACCESSION_ID:"4HHB"' in query
        assert "ACCESSION_TYPE:pdb" in query

    def test_request_exception_returns_none_not_zero(self):
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("network down")

        assert fetch_literature_count("4HHB", session=session) is None

    def test_http_error_status_returns_none(self):
        session = MagicMock()
        response = _mock_response()
        response.raise_for_status.side_effect = requests.HTTPError("500")
        session.get.return_value = response

        assert fetch_literature_count("4HHB", session=session) is None

    def test_malformed_json_returns_none(self):
        session = MagicMock()
        session.get.return_value = _mock_response(json_ok=False)

        assert fetch_literature_count("4HHB", session=session) is None

    @pytest.mark.parametrize(
        "payload",
        [{}, {"hitCount": None}, {"hitCount": "not a number"}],
        ids=["missing_key", "null_value", "wrong_type"],
    )
    def test_missing_or_malformed_hit_count_returns_none(self, payload):
        session = MagicMock()
        response = _mock_response()
        response.json.return_value = payload
        session.get.return_value = response

        assert fetch_literature_count("4HHB", session=session) is None

    def test_uses_module_level_requests_when_no_session_given(self):
        with patch("protein_selector.domain.bioinformatics.literature.requests") as mock_requests:
            mock_requests.get.return_value = _mock_response(hit_count=5)
            mock_requests.RequestException = requests.RequestException

            result = fetch_literature_count("4HHB")

        assert result == 5
        mock_requests.get.assert_called_once()


class TestFetchLiteratureCounts:
    def test_empty_input_returns_empty_dict(self):
        assert fetch_literature_counts([]) == {}

    def test_fetches_one_result_per_pdb_id_reusing_one_session(self):
        with patch("protein_selector.domain.bioinformatics.literature.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.get.side_effect = [
                _mock_response(hit_count=39),
                _mock_response(hit_count=2),
            ]
            mock_session_cls.return_value.__enter__.return_value = mock_session

            result = fetch_literature_counts(["4HHB", "1STP"])

        assert result == {"4HHB": 39, "1STP": 2}
        assert mock_session_cls.call_count == 1  # one Session for the whole batch

    def test_per_id_failures_surface_as_none_not_dropped(self):
        with patch("protein_selector.domain.bioinformatics.literature.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.get.side_effect = [
                _mock_response(hit_count=39),
                requests.ConnectionError("down"),
            ]
            mock_session_cls.return_value.__enter__.return_value = mock_session

            result = fetch_literature_counts(["4HHB", "BAD_ID"])

        assert result == {"4HHB": 39, "BAD_ID": None}
