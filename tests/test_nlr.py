"""Tests for NLR (NREL) source connector."""

from unittest.mock import MagicMock, patch

from pipeline.sources.nlr import NLRSource


def _make_solar_resource_response():
    """Build a mock Solar Resource Data API response."""
    return {
        "outputs": {
            "avg_dni": {
                "annual": 6.06,
                "monthly": {
                    "jan": 4.5, "feb": 5.2, "mar": 6.0, "apr": 6.8,
                    "may": 7.2, "jun": 7.8, "jul": 7.5, "aug": 7.0,
                    "sep": 6.5, "oct": 5.5, "nov": 4.8, "dec": 4.0,
                },
            },
            "avg_ghi": {
                "annual": 4.81,
                "monthly": {
                    "jan": 2.5, "feb": 3.2, "mar": 4.0, "apr": 5.2,
                    "may": 6.0, "jun": 6.5, "jul": 6.3, "aug": 5.8,
                    "sep": 5.0, "oct": 3.8, "nov": 2.8, "dec": 2.2,
                },
            },
            "avg_lat_tilt": {
                "annual": 5.82,
                "monthly": {
                    "jan": 4.0, "feb": 4.8, "mar": 5.5, "apr": 6.0,
                    "may": 6.5, "jun": 6.8, "jul": 6.6, "aug": 6.2,
                    "sep": 5.8, "oct": 5.0, "nov": 4.2, "dec": 3.5,
                },
            },
        },
        "inputs": {"lat": "33.45", "lon": "-112.07"},
        "version": "1.0.0",
    }


def _make_pvwatts_response():
    """Build a mock PVWatts V6 API response."""
    return {
        "outputs": {
            "ac_annual": 1642000.0,
            "capacity_factor": 18.7,
            "solrad_annual": 5.62,
            "solrad_monthly": [3.5, 4.2, 5.0, 6.0, 6.5, 7.0, 6.8, 6.3, 5.5, 4.5, 3.8, 3.2],
            "ac_monthly": [110000, 120000, 140000, 150000, 160000, 165000, 160000, 155000, 140000, 125000, 112000, 105000],
        },
        "station_info": {
            "lat": 33.45,
            "lon": -112.07,
            "city": "Phoenix",
            "state": "Arizona",
            "distance": 1500,
        },
        "inputs": {"system_capacity": "1000"},
    }


@patch("pipeline.sources.nlr.get_cached", return_value=None)
@patch("pipeline.sources.nlr.set_cached")
@patch("pipeline.sources.nlr.requests")
def test_fetch_constructs_url_and_caches(mock_requests, mock_set, mock_get):
    """fetch() calls the API with api_key and caches the response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"outputs": {}}
    mock_requests.get.return_value = mock_resp

    source = NLRSource(api_key="test-key")
    result = source.fetch("/solar/solar_resource/v1.json", lat=33.45, lon=-112.07)

    call_args = mock_requests.get.call_args
    assert "api_key" in call_args.kwargs.get("params", {}) or "api_key" in call_args[1].get("params", {})
    assert mock_set.called


@patch("pipeline.sources.nlr.get_cached", return_value={"outputs": {}})
def test_fetch_returns_cached(mock_get):
    """fetch() returns cached response."""
    source = NLRSource(api_key="test-key")
    result = source.fetch("/solar/solar_resource/v1.json", lat=33.45, lon=-112.07)
    assert result == {"outputs": {}}


@patch.object(NLRSource, "fetch", return_value=_make_solar_resource_response())
def test_get_generation_context_solar_resource(mock_fetch):
    """get_generation_context returns solar resource data for a US state."""
    source = NLRSource(api_key="test-key")
    result = source.get_generation_context("Arizona", data_types=["solar_resource"])

    assert result["entity"] == "Arizona"
    assert result["source"] == "nlr"
    solar = result["solar_resource"]
    assert solar["avg_ghi"]["annual"] == 4.81
    assert solar["avg_dni"]["annual"] == 6.06
    assert solar["avg_lat_tilt"]["annual"] == 5.82
    assert "jan" in solar["avg_ghi"]["monthly"]
    assert "pvwatts_estimate" not in result


@patch.object(NLRSource, "fetch", return_value=_make_pvwatts_response())
def test_get_generation_context_pvwatts(mock_fetch):
    """get_generation_context returns PVWatts estimate."""
    source = NLRSource(api_key="test-key")
    result = source.get_generation_context("California", data_types=["pvwatts_estimate"])

    assert "pvwatts_estimate" in result
    pv = result["pvwatts_estimate"]
    assert pv["system_capacity_kw"] == 1000
    assert pv["ac_annual_kwh"] == 1642000.0
    assert pv["capacity_factor_pct"] == 18.7
    assert pv["solrad_annual"] == 5.62
    assert len(pv["solrad_monthly"]) == 12
    assert "solar_resource" not in result


@patch.object(NLRSource, "fetch")
def test_get_generation_context_all_types(mock_fetch):
    """get_generation_context returns both types when none specified."""
    mock_fetch.side_effect = [
        _make_solar_resource_response(),
        _make_pvwatts_response(),
    ]
    source = NLRSource(api_key="test-key")
    result = source.get_generation_context("Texas")

    assert "solar_resource" in result
    assert "pvwatts_estimate" in result


def test_get_generation_context_non_us_entity():
    """Non-US entity returns empty dict."""
    source = NLRSource(api_key="test-key")
    result = source.get_generation_context("Germany")
    assert result == {}


def test_get_generation_context_us_national():
    """'United States' entity is accepted."""
    with patch.object(NLRSource, "fetch", return_value=_make_solar_resource_response()):
        source = NLRSource(api_key="test-key")
        result = source.get_generation_context("United States", data_types=["solar_resource"])
        assert result["entity"] == "United States"
        assert "solar_resource" in result
