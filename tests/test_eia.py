"""Tests for the EIA API connector."""

from unittest.mock import patch, MagicMock

from pipeline.sources.eia import EIASource


@patch("pipeline.sources.eia.get_cached", return_value=None)
@patch("pipeline.sources.eia.set_cached")
@patch("pipeline.sources.eia.requests")
def test_fetch_constructs_url_and_caches(mock_requests, mock_set, mock_get):
    """fetch() builds the correct URL and caches the response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"response": {"data": [{"period": "2023"}]}}
    mock_requests.get.return_value = mock_resp

    eia = EIASource(api_key="test-key")
    result = eia.fetch("international/data", **{"facets[countryRegionId][]": "DEU"})

    call_url = mock_requests.get.call_args.args[0]
    assert "api.eia.gov/v2/international/data" in call_url
    assert result["response"]["data"][0]["period"] == "2023"
    mock_set.assert_called_once()


@patch("pipeline.sources.eia.get_cached", return_value={"response": {"data": []}})
def test_fetch_returns_cached_response(mock_get):
    """fetch() returns cached data without hitting the API."""
    eia = EIASource(api_key="test-key")
    result = eia.fetch("international/data")
    assert result == {"response": {"data": []}}


def test_get_generation_context_skips_non_us():
    """get_generation_context returns empty generation for non-US countries."""
    eia = EIASource(api_key="test-key")
    result = eia.get_generation_context("Germany")

    assert result["entity"] == "Germany"
    assert result["source"] == "eia"
    assert result["generation"] == []


@patch("pipeline.sources.eia.get_cached", return_value=None)
@patch("pipeline.sources.eia.set_cached")
@patch("pipeline.sources.eia.requests")
def test_get_generation_context_us_national(mock_requests, mock_set, mock_get):
    """get_generation_context fetches US national data."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "response": {
            "data": [
                {"period": "2023", "fueltypeid": "SUN", "fuelTypeDescription": "Solar", "generation": "5432.1"},
            ]
        }
    }
    mock_requests.get.return_value = mock_resp

    eia = EIASource(api_key="test-key")
    result = eia.get_generation_context("United States")

    assert result["entity"] == "United States"
    assert result["source"] == "eia"
    assert result["generation"][0]["fuel_type"] == "SUN"

    # Should use location=US facet
    call_params = mock_requests.get.call_args.kwargs["params"]
    assert call_params.get("facets[location][]") == "US"


@patch("pipeline.sources.eia.get_cached", return_value=None)
@patch("pipeline.sources.eia.set_cached")
@patch("pipeline.sources.eia.requests")
def test_get_generation_context_us_state(mock_requests, mock_set, mock_get):
    """get_generation_context fetches state-level data for US states."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "response": {
            "data": [
                {"period": "2023", "fueltypeid": "SUN", "fuelTypeDescription": "Solar", "generation": "5432.1"},
            ]
        }
    }
    mock_requests.get.return_value = mock_resp

    eia = EIASource(api_key="test-key")
    result = eia.get_generation_context("California")

    assert result["entity"] == "California"
    assert result["source"] == "eia"
    assert result["generation"][0]["fuel_type"] == "SUN"

    # Verify state abbreviation is used, not full name
    call_params = mock_requests.get.call_args.kwargs["params"]
    assert call_params.get("facets[location][]") == "CA"
