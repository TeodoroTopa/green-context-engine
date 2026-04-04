"""Tests for the NOAA Climate Data Online connector."""

from unittest.mock import patch, MagicMock

from pipeline.sources.noaa import NOAASource


@patch("pipeline.sources.noaa.get_cached", return_value=None)
@patch("pipeline.sources.noaa.set_cached")
@patch("pipeline.sources.noaa.requests")
def test_fetch_constructs_url_and_caches(mock_requests, mock_set, mock_get):
    """fetch() builds the correct URL and caches the response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": [{"value": 250}]}
    mock_requests.get.return_value = mock_resp

    noaa = NOAASource(api_key="test-token")
    result = noaa.fetch("data", datasetid="GSOM", locationid="FIPS:US")

    call_url = mock_requests.get.call_args.args[0]
    assert "ncei.noaa.gov/cdo-web/api/v2/data" in call_url
    assert result["results"][0]["value"] == 250
    mock_set.assert_called_once()


@patch("pipeline.sources.noaa.get_cached", return_value=None)
@patch("pipeline.sources.noaa.set_cached")
@patch("pipeline.sources.noaa.requests")
def test_fetch_sends_token_header(mock_requests, mock_set, mock_get):
    """fetch() includes token header when key is set."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"results": []}
    mock_requests.get.return_value = mock_resp

    noaa = NOAASource(api_key="my-noaa-token")
    noaa.fetch("data")

    headers = mock_requests.get.call_args.kwargs.get("headers", {})
    assert headers.get("token") == "my-noaa-token"


@patch("pipeline.sources.noaa.get_cached", return_value=None)
@patch("pipeline.sources.noaa.set_cached")
@patch("pipeline.sources.noaa.requests")
def test_get_generation_context_returns_climate_data(mock_requests, mock_set, mock_get):
    """get_generation_context returns station-averaged temperature and precipitation."""
    import requests as real_requests
    mock_requests.RequestException = real_requests.RequestException

    # Simulate multiple stations for the same month (GSOM returns per-station)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "results": [
            {"datatype": "TAVG", "date": "2024-06-01T00:00:00", "station": "S1", "value": 22.0},
            {"datatype": "TAVG", "date": "2024-06-01T00:00:00", "station": "S2", "value": 24.0},
            {"datatype": "TMAX", "date": "2024-06-01T00:00:00", "station": "S1", "value": 31.0},
            {"datatype": "PRCP", "date": "2024-06-01T00:00:00", "station": "S1", "value": 85.0},
            {"datatype": "PRCP", "date": "2024-06-01T00:00:00", "station": "S2", "value": 90.0},
        ]
    }
    mock_requests.get.return_value = mock_resp

    noaa = NOAASource(api_key="test-token")
    result = noaa.get_generation_context("Germany")

    assert result["entity"] == "Germany"
    assert result["source"] == "noaa"
    # TAVG: avg of 22.0 and 24.0 = 23.0 (no /10 — GSOM is already in °C)
    tavg = [t for t in result["temperature"] if t["type"] == "TAVG"]
    assert len(tavg) == 1
    assert tavg[0]["value_celsius"] == 23.0
    # TMAX: only 1 station = 31.0
    tmax = [t for t in result["temperature"] if t["type"] == "TMAX"]
    assert len(tmax) == 1
    assert tmax[0]["value_celsius"] == 31.0
    # PRCP: avg of 85.0 and 90.0 = 87.5
    assert len(result["precipitation"]) == 1
    assert result["precipitation"][0]["value_mm"] == 87.5


def test_get_generation_context_unknown_country():
    """Returns empty data for countries not in the FIPS mapping."""
    noaa = NOAASource(api_key="test-token")
    result = noaa.get_generation_context("Atlantis")

    assert result["entity"] == "Atlantis"
    assert result["temperature"] == []
    assert result["precipitation"] == []
    assert result["source"] == "noaa"


def test_get_generation_context_us_state():
    """US states are resolved via US_STATE_FIPS, not COUNTRY_FIPS."""
    noaa = NOAASource(api_key="test-token")
    # Just verify the FIPS lookup works — don't hit the API
    from pipeline.sources.noaa import US_STATE_FIPS
    assert "California" in US_STATE_FIPS
    assert US_STATE_FIPS["California"] == "FIPS:06"


@patch("pipeline.sources.noaa.get_cached", return_value={"results": [{"value": 100}]})
def test_fetch_returns_cached(mock_get):
    """fetch() returns cached data without hitting the API."""
    noaa = NOAASource(api_key="test-token")
    result = noaa.fetch("data")
    assert result == {"results": [{"value": 100}]}
