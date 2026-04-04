"""Tests for the Global Forest Watch connector."""

from unittest.mock import patch, MagicMock

from pipeline.sources.gfw import GFWSource


@patch("pipeline.sources.gfw.get_cached", return_value=None)
@patch("pipeline.sources.gfw.set_cached")
@patch("pipeline.sources.gfw.requests")
def test_fetch_constructs_url_and_caches(mock_requests, mock_set, mock_get):
    """fetch() builds the correct URL and caches the response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": [{"year": 2023, "loss_ha": 50000}]}
    mock_requests.get.return_value = mock_resp

    gfw = GFWSource(api_key="test-key")
    result = gfw.fetch("dataset/umd_tree_cover_loss/v1.11/query/json", sql="SELECT *")

    call_url = mock_requests.get.call_args.args[0]
    assert "data-api.globalforestwatch.org" in call_url
    assert result["data"][0]["year"] == 2023
    mock_set.assert_called_once()


@patch("pipeline.sources.gfw.get_cached", return_value=None)
@patch("pipeline.sources.gfw.set_cached")
@patch("pipeline.sources.gfw.requests")
def test_fetch_sends_api_key_header(mock_requests, mock_set, mock_get):
    """fetch() includes x-api-key header when key is set."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": []}
    mock_requests.get.return_value = mock_resp

    gfw = GFWSource(api_key="my-secret-key")
    gfw.fetch("dataset/test/v1/query/json")

    headers = mock_requests.get.call_args.kwargs.get("headers", {})
    assert headers.get("x-api-key") == "my-secret-key"


@patch("pipeline.sources.gfw.get_cached", return_value=None)
@patch("pipeline.sources.gfw.set_cached")
@patch("pipeline.sources.gfw.requests")
def test_get_generation_context_returns_loss_data(mock_requests, mock_set, mock_get):
    """get_generation_context returns structured tree cover loss for a known country."""
    import requests as real_requests
    mock_requests.RequestException = real_requests.RequestException

    # Two GET calls: geostore lookup, then query
    geostore_resp = MagicMock()
    geostore_resp.json.return_value = {"data": {"id": "fake-geostore-id"}}

    query_resp = MagicMock()
    query_resp.json.return_value = {
        "data": [
            {"umd_tree_cover_loss__year": 2024, "loss_ha": 120000},
            {"umd_tree_cover_loss__year": 2023, "loss_ha": 72000},
        ]
    }
    mock_requests.get.side_effect = [geostore_resp, query_resp]

    gfw = GFWSource(api_key="test-key")
    result = gfw.get_generation_context("Indonesia")

    assert result["entity"] == "Indonesia"
    assert result["source"] == "gfw"
    assert len(result["tree_cover_loss"]) == 2
    assert result["tree_cover_loss"][0]["year"] == 2024
    assert result["tree_cover_loss"][0]["loss_ha"] == 120000


def test_get_generation_context_unknown_country():
    """Returns empty data for countries not in the ISO mapping."""
    gfw = GFWSource(api_key="test-key")
    result = gfw.get_generation_context("Atlantis")

    assert result["entity"] == "Atlantis"
    assert result["tree_cover_loss"] == []
    assert result["source"] == "gfw"


@patch("pipeline.sources.gfw.get_cached", return_value={"data": [{"loss_ha": 50000}]})
def test_fetch_returns_cached(mock_get):
    """fetch() returns cached data without hitting the API."""
    gfw = GFWSource(api_key="test-key")
    result = gfw.fetch("dataset/test/v1/query/json")
    assert result == {"data": [{"loss_ha": 50000}]}
