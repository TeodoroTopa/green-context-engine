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


@patch("pipeline.sources.eia.get_cached", return_value=None)
@patch("pipeline.sources.eia.set_cached")
@patch("pipeline.sources.eia.requests")
def test_get_generation_context_international(mock_requests, mock_set, mock_get):
    """get_generation_context returns structured data for a known country."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "response": {
            "data": [
                {"period": "2023", "productId": 38, "productName": "Wind", "value": 145.2, "unit": "billion kWh"},
                {"period": "2023", "productId": 39, "productName": "Solar", "value": 61.8, "unit": "billion kWh"},
            ]
        }
    }
    mock_requests.get.return_value = mock_resp

    eia = EIASource(api_key="test-key")
    result = eia.get_generation_context("Germany")

    assert result["entity"] == "Germany"
    assert result["source"] == "eia"
    assert len(result["generation"]) == 2
    assert result["generation"][0]["fuel_type"] == "Wind"
    assert result["generation"][0]["value"] == 145.2


@patch("pipeline.sources.eia.get_cached", return_value=None)
@patch("pipeline.sources.eia.set_cached")
@patch("pipeline.sources.eia.requests")
def test_get_generation_context_us_state(mock_requests, mock_set, mock_get):
    """get_generation_context falls back to US state endpoint for unknown country codes."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "response": {
            "data": [
                {"period": "2023", "fueltypeid": "SUN", "fueltypedescription": "Solar", "generation": "5432.1"},
            ]
        }
    }
    mock_requests.get.return_value = mock_resp

    eia = EIASource(api_key="test-key")
    result = eia.get_generation_context("California")

    assert result["entity"] == "California"
    assert result["source"] == "eia"
    assert result["generation"][0]["fuel_type"] == "SUN"
    assert result["generation"][0]["value"] == "5432.1"
