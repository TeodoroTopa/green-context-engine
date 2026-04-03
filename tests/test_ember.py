"""Tests for the Ember API source connector."""

from unittest.mock import MagicMock, patch

import pytest

from pipeline.sources.ember import EmberSource


# --- Fixtures ---

SAMPLE_GENERATION_RESPONSE = {
    "stats": {"number_of_records": 2},
    "data": [
        {
            "entity": "Germany",
            "entity_code": "DEU",
            "date": "2023",
            "series": "Solar",
            "generation_twh": 61.2,
            "share_of_generation_pct": 12.1,
        },
        {
            "entity": "Germany",
            "entity_code": "DEU",
            "date": "2023",
            "series": "Wind",
            "generation_twh": 139.3,
            "share_of_generation_pct": 27.5,
        },
    ],
}

SAMPLE_CARBON_RESPONSE = {
    "stats": {"number_of_records": 1},
    "data": [
        {
            "entity": "Germany",
            "entity_code": "DEU",
            "date": "2023",
            "emissions_intensity_gco2_per_kwh": 385.0,
        },
    ],
}


@pytest.fixture
def ember(tmp_path, monkeypatch):
    """EmberSource with cache pointed at a temp directory."""
    monkeypatch.setattr("pipeline.sources.cache.CACHE_DIR", tmp_path)
    return EmberSource(api_key="test-key", cache_ttl=3600)


# --- Tests ---


@patch("pipeline.sources.ember.requests.get")
def test_fetch_constructs_correct_url(mock_get, ember):
    """fetch() calls the right URL with the right params."""
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_GENERATION_RESPONSE
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    result = ember.fetch("electricity-generation/yearly", entity="Germany", start_date="2020")

    mock_get.assert_called_once()
    call_args = mock_get.call_args
    assert call_args[0][0] == "https://api.ember-energy.org/v1/electricity-generation/yearly"
    assert call_args[1]["params"]["entity"] == "Germany"
    assert call_args[1]["params"]["start_date"] == "2020"
    assert call_args[1]["params"]["api_key"] == "test-key"
    assert result == SAMPLE_GENERATION_RESPONSE


@patch("pipeline.sources.ember.requests.get")
def test_fetch_uses_cache_on_second_call(mock_get, ember):
    """Second call with same params should hit cache, not the API."""
    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_GENERATION_RESPONSE
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    # First call — hits API
    result1 = ember.fetch("electricity-generation/yearly", entity="Germany")
    assert mock_get.call_count == 1

    # Second call — should use cache
    result2 = ember.fetch("electricity-generation/yearly", entity="Germany")
    assert mock_get.call_count == 1  # still 1, no new API call
    assert result1 == result2


@patch("pipeline.sources.ember.requests.get")
def test_fetch_without_api_key(mock_get, tmp_path, monkeypatch):
    """fetch() works without an API key (doesn't include it in params)."""
    monkeypatch.setattr("pipeline.sources.cache.CACHE_DIR", tmp_path)
    ember_no_key = EmberSource(api_key=None)

    mock_response = MagicMock()
    mock_response.json.return_value = {"stats": {}, "data": []}
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    ember_no_key.fetch("carbon-intensity/yearly", entity="World")

    call_params = mock_get.call_args[1]["params"]
    assert "api_key" not in call_params


@patch("pipeline.sources.ember.requests.get")
def test_get_generation_context(mock_get, ember):
    """get_generation_context() combines generation + carbon intensity data."""
    # Mock returns different data for the two endpoints
    def side_effect(url, **kwargs):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        if "electricity-generation" in url:
            mock_resp.json.return_value = SAMPLE_GENERATION_RESPONSE
        else:
            mock_resp.json.return_value = SAMPLE_CARBON_RESPONSE
        return mock_resp

    mock_get.side_effect = side_effect

    result = ember.get_generation_context("Germany", start_date="2023")

    assert result["entity"] == "Germany"
    assert len(result["generation"]) == 2
    assert result["generation"][0]["series"] == "Solar"
    assert len(result["carbon_intensity"]) == 1
    assert result["carbon_intensity"][0]["emissions_intensity_gco2_per_kwh"] == 385.0
    # Should have made 2 API calls (generation + carbon intensity)
    assert mock_get.call_count == 2


@patch("pipeline.sources.ember.requests.get")
def test_get_monthly_trend(mock_get, ember):
    """get_monthly_trend() calls the monthly endpoint with a computed start date."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"stats": {}, "data": []}
    mock_response.raise_for_status = MagicMock()
    mock_get.return_value = mock_response

    ember.get_monthly_trend("Germany", months=6)

    call_args = mock_get.call_args
    assert "electricity-generation/monthly" in call_args[0][0]
    # start_date should be roughly 6 months ago
    assert "start_date" in call_args[1]["params"]


@patch("pipeline.sources.ember.requests.get")
def test_fetch_raises_on_http_error(mock_get, ember):
    """fetch() propagates HTTP errors."""
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("403 Forbidden")
    mock_get.return_value = mock_response

    with pytest.raises(Exception, match="403 Forbidden"):
        ember.fetch("electricity-generation/yearly", entity="Germany")
