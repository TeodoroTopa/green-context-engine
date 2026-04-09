"""Tests for Open-Meteo source connector."""

from unittest.mock import MagicMock, patch

from pipeline.sources.openmeteo import OpenMeteoSource, BASE_URL


def _make_daily_response(year=2025, days=365):
    """Build a mock Open-Meteo daily response."""
    dates = [f"{year}-01-01"] * days  # simplified
    return {
        "daily": {
            "time": dates,
            "shortwave_radiation_sum": [18.0] * days,  # MJ/m2
            "sunshine_duration": [28800.0] * days,  # 8 hours in seconds
            "mean_wind_speed_10m": [12.5] * days,
            "wind_speed_10m_max": [25.0] * days,
            "temperature_2m_mean": [22.0] * days,
            "temperature_2m_max": [35.0] * days,
            "temperature_2m_min": [10.0] * days,
            "precipitation_sum": [2.0] * days,
            "et0_fao_evapotranspiration": [4.5] * days,  # mm/day
        }
    }


@patch("pipeline.sources.openmeteo.get_cached", return_value=None)
@patch("pipeline.sources.openmeteo.set_cached")
@patch("pipeline.sources.openmeteo.requests")
def test_fetch_constructs_url_and_caches(mock_requests, mock_set, mock_get):
    """fetch() calls the API and caches the response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"daily": {}}
    mock_requests.get.return_value = mock_resp

    source = OpenMeteoSource()
    result = source.fetch(BASE_URL, latitude=51.5, longitude=-0.1)

    mock_requests.get.assert_called_once()
    assert mock_set.called
    assert result == {"daily": {}}


@patch("pipeline.sources.openmeteo.get_cached", return_value={"daily": {}})
def test_fetch_returns_cached(mock_get):
    """fetch() returns cached response without hitting the API."""
    source = OpenMeteoSource()
    result = source.fetch(BASE_URL, latitude=51.5, longitude=-0.1)
    assert result == {"daily": {}}


@patch.object(OpenMeteoSource, "fetch", return_value=_make_daily_response())
def test_get_generation_context_solar_radiation(mock_fetch):
    """get_generation_context returns solar radiation with GHI, DNI, and sunshine."""
    source = OpenMeteoSource()
    result = source.get_generation_context("Indonesia", data_types=["solar_radiation"])

    assert result["entity"] == "Indonesia"
    assert result["source"] == "openmeteo"
    solar = result["solar_radiation"]
    # 18 MJ/m2 / 3.6 = 5.0 kWh/m2/day
    assert solar["avg_daily_ghi_kwh_m2"] == 5.0
    # Sunshine: 28800 seconds / 3600 = 8.0 hours
    assert solar["avg_sunshine_hours"] == 8.0
    assert "wind_speed" not in result


@patch.object(OpenMeteoSource, "fetch", return_value=_make_daily_response())
def test_get_generation_context_wind_speed(mock_fetch):
    """get_generation_context returns wind speed at 10m and 100m hub height."""
    source = OpenMeteoSource()
    result = source.get_generation_context("Germany", data_types=["wind_speed"])

    assert result["entity"] == "Germany"
    wind = result["wind_speed"]
    assert wind["avg_10m_kmh"] == 12.5
    assert wind["max_10m_kmh"] == 25.0
    assert "solar_radiation" not in result


@patch.object(OpenMeteoSource, "fetch", return_value=_make_daily_response())
def test_get_generation_context_evapotranspiration(mock_fetch):
    """get_generation_context returns evapotranspiration data."""
    source = OpenMeteoSource()
    result = source.get_generation_context("Brazil", data_types=["evapotranspiration"])

    assert "evapotranspiration" in result
    et = result["evapotranspiration"]
    assert et["avg_daily_mm"] == 4.5
    # 4.5 mm/day * 365 days = 1642.5 mm total
    assert et["total_mm"] == 1642.5


@patch.object(OpenMeteoSource, "fetch", return_value=_make_daily_response())
def test_get_generation_context_all_types(mock_fetch):
    """get_generation_context returns all data types when none specified."""
    source = OpenMeteoSource()
    result = source.get_generation_context("Australia")

    assert "solar_radiation" in result
    assert "wind_speed" in result
    assert "temperature" in result
    assert "precipitation" in result
    assert "evapotranspiration" in result


def test_get_generation_context_unknown_country():
    """Unknown country returns empty dict."""
    source = OpenMeteoSource()
    result = source.get_generation_context("Narnia")
    assert result == {}
