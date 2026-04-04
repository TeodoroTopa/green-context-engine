"""Tests for the Electricity Maps connector."""

from unittest.mock import patch, MagicMock

from pipeline.sources.electricity_maps import ElectricityMapsSource


@patch("pipeline.sources.electricity_maps.get_cached", return_value=None)
@patch("pipeline.sources.electricity_maps.set_cached")
@patch("pipeline.sources.electricity_maps.requests")
def test_fetch_constructs_url_and_caches(mock_requests, mock_set, mock_get):
    """fetch() builds the correct URL and caches the response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"carbonIntensity": 302, "zone": "DE"}
    mock_requests.get.return_value = mock_resp

    em = ElectricityMapsSource(api_key="test-key")
    result = em.fetch("v3/carbon-intensity/latest", zone="DE")

    call_url = mock_requests.get.call_args.args[0]
    assert "api.electricitymaps.com" in call_url
    assert result["carbonIntensity"] == 302
    mock_set.assert_called_once()


@patch("pipeline.sources.electricity_maps.get_cached", return_value=None)
@patch("pipeline.sources.electricity_maps.set_cached")
@patch("pipeline.sources.electricity_maps.requests")
def test_fetch_sends_auth_token_header(mock_requests, mock_set, mock_get):
    """fetch() includes auth-token header when key is set."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}
    mock_requests.get.return_value = mock_resp

    em = ElectricityMapsSource(api_key="my-auth-token")
    em.fetch("v3/carbon-intensity/latest", zone="DE")

    headers = mock_requests.get.call_args.kwargs.get("headers", {})
    assert headers.get("auth-token") == "my-auth-token"


@patch("pipeline.sources.electricity_maps.get_cached", return_value=None)
@patch("pipeline.sources.electricity_maps.set_cached")
@patch("pipeline.sources.electricity_maps.requests")
def test_get_generation_context_returns_zone_data(mock_requests, mock_set, mock_get):
    """get_generation_context returns carbon intensity and power breakdown."""
    import requests as real_requests
    mock_requests.RequestException = real_requests.RequestException

    ci_resp = MagicMock()
    ci_resp.json.return_value = {
        "carbonIntensity": 302,
        "datetime": "2026-04-04T12:00:00Z",
        "zone": "DE",
    }

    pb_resp = MagicMock()
    pb_resp.json.return_value = {
        "powerConsumptionBreakdown": {
            "wind": 15000,
            "solar": 8000,
            "coal": 12000,
            "gas": 5000,
            "nuclear": 0,
            "hydro": None,
        }
    }
    mock_requests.get.side_effect = [ci_resp, pb_resp]

    em = ElectricityMapsSource(api_key="test-key")
    result = em.get_generation_context("Germany")

    assert result["entity"] == "Germany"
    assert result["source"] == "electricity_maps"
    assert result["carbon_intensity_realtime"] == 302
    assert result["datetime"] == "2026-04-04T12:00:00Z"
    # Nuclear (0) and hydro (None) should be filtered out
    assert "nuclear" not in result["power_breakdown"]
    assert "hydro" not in result["power_breakdown"]
    assert result["power_breakdown"]["wind"] == 15000


def test_get_generation_context_unknown_zone():
    """Returns empty data for countries not in the zone mapping."""
    em = ElectricityMapsSource(api_key="test-key")
    result = em.get_generation_context("Atlantis")

    assert result["entity"] == "Atlantis"
    assert result["carbon_intensity_realtime"] is None
    assert result["power_breakdown"] == {}
    assert result["source"] == "electricity_maps"


@patch("pipeline.sources.electricity_maps.get_cached", return_value={"carbonIntensity": 150})
def test_fetch_returns_cached(mock_get):
    """fetch() returns cached data without hitting the API."""
    em = ElectricityMapsSource(api_key="test-key")
    result = em.fetch("v3/carbon-intensity/latest", zone="SE")
    assert result == {"carbonIntensity": 150}
