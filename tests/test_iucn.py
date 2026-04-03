"""Tests for the IUCN Red List connector."""

from unittest.mock import patch, MagicMock

from pipeline.sources.iucn import IUCNSource


@patch("pipeline.sources.iucn.get_cached", return_value=None)
@patch("pipeline.sources.iucn.set_cached")
@patch("pipeline.sources.iucn.requests")
def test_fetch_sends_bearer_token(mock_requests, mock_set, mock_get):
    """fetch() includes Authorization: Bearer header."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"assessments": []}
    mock_requests.get.return_value = mock_resp

    iucn = IUCNSource(api_key="my-token")
    iucn.fetch("countries/ID")

    headers = mock_requests.get.call_args.kwargs.get("headers", {})
    assert headers.get("Authorization") == "Bearer my-token"


@patch("pipeline.sources.iucn.get_cached", return_value=None)
@patch("pipeline.sources.iucn.set_cached")
@patch("pipeline.sources.iucn.requests")
def test_get_generation_context_counts_categories(mock_requests, mock_set, mock_get):
    """get_generation_context returns threatened species counts by category."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "assessments": [
            {"red_list_category": {"code": "CR"}},
            {"red_list_category": {"code": "EN"}},
            {"red_list_category": {"code": "EN"}},
            {"red_list_category": {"code": "VU"}},
            {"red_list_category": {"code": "LC"}},
        ]
    }
    mock_requests.get.return_value = mock_resp

    iucn = IUCNSource(api_key="test-key")
    result = iucn.get_generation_context("Indonesia")

    assert result["entity"] == "Indonesia"
    assert result["source"] == "iucn"
    assert result["total_assessed"] == 5
    assert result["threatened_species"]["CR"] == 1
    assert result["threatened_species"]["EN"] == 2
    assert result["threatened_species"]["VU"] == 1
    assert result["threatened_species"]["LC"] == 1


def test_get_generation_context_unknown_country():
    """Returns empty data for countries not in the ISO mapping."""
    iucn = IUCNSource(api_key="test-key")
    result = iucn.get_generation_context("Atlantis")

    assert result["entity"] == "Atlantis"
    assert result["threatened_species"] == {}
    assert result["total_assessed"] == 0


@patch("pipeline.sources.iucn.get_cached", return_value=None)
@patch("pipeline.sources.iucn.set_cached")
@patch("pipeline.sources.iucn.requests")
def test_pagination_stops_on_partial_page(mock_requests, mock_set, mock_get):
    """Pagination stops when a page has fewer than 100 results."""
    mock_resp = MagicMock()
    # Return 3 results (< 100), so no second page
    mock_resp.json.return_value = {
        "assessments": [
            {"red_list_category": {"code": "CR"}},
            {"red_list_category": {"code": "EN"}},
            {"red_list_category": {"code": "VU"}},
        ]
    }
    mock_requests.get.return_value = mock_resp

    iucn = IUCNSource(api_key="test-key")
    result = iucn.get_generation_context("Brazil")

    # Only one API call (no second page)
    assert mock_requests.get.call_count == 1
    assert result["total_assessed"] == 3


@patch("pipeline.sources.iucn.get_cached", return_value={"assessments": [{"red_list_category": {"code": "CR"}}]})
def test_fetch_returns_cached(mock_get):
    """fetch() returns cached data without hitting the API."""
    iucn = IUCNSource(api_key="test-key")
    result = iucn.fetch("countries/ID")
    assert result == {"assessments": [{"red_list_category": {"code": "CR"}}]}
