"""Tests for the Ember API source connector."""

from unittest.mock import MagicMock, patch

from pipeline.sources.ember import EmberSource

SAMPLE_GENERATION_RESPONSE = {
    "stats": {"number_of_records": 2},
    "data": [
        {"entity": "Germany", "date": "2023", "series": "Solar", "generation_twh": 61.2},
        {"entity": "Germany", "date": "2023", "series": "Wind", "generation_twh": 139.3},
    ],
}

SAMPLE_CARBON_RESPONSE = {
    "stats": {"number_of_records": 1},
    "data": [
        {"entity": "Germany", "date": "2023", "emissions_intensity_gco2_per_kwh": 385.0},
    ],
}


def _mock_response(data):
    resp = MagicMock()
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


@patch("pipeline.sources.ember.requests.get")
def test_fetch_constructs_url_and_caches(mock_get, tmp_path, monkeypatch):
    """fetch() hits the right URL with params, and second call uses cache."""
    monkeypatch.setattr("pipeline.sources.cache.CACHE_DIR", tmp_path)
    ember = EmberSource(api_key="test-key")

    mock_get.return_value = _mock_response(SAMPLE_GENERATION_RESPONSE)

    result = ember.fetch("electricity-generation/yearly", entity="Germany", start_date="2020")
    assert result == SAMPLE_GENERATION_RESPONSE
    assert mock_get.call_args[0][0] == "https://api.ember-energy.org/v1/electricity-generation/yearly"
    assert mock_get.call_args[1]["params"]["api_key"] == "test-key"

    # Second call — cache hit, no new API call
    ember.fetch("electricity-generation/yearly", entity="Germany", start_date="2020")
    assert mock_get.call_count == 1


@patch("pipeline.sources.ember.requests.get")
def test_get_generation_context_combines_two_calls(mock_get, tmp_path, monkeypatch):
    """get_generation_context() merges generation + carbon intensity data."""
    monkeypatch.setattr("pipeline.sources.cache.CACHE_DIR", tmp_path)
    ember = EmberSource()

    def side_effect(url, **kwargs):
        if "electricity-generation" in url:
            return _mock_response(SAMPLE_GENERATION_RESPONSE)
        return _mock_response(SAMPLE_CARBON_RESPONSE)

    mock_get.side_effect = side_effect

    result = ember.get_generation_context("Germany")
    assert result["entity"] == "Germany"
    assert len(result["generation"]) == 2
    assert result["carbon_intensity"][0]["emissions_intensity_gco2_per_kwh"] == 385.0
    assert mock_get.call_count == 2
