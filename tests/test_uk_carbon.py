"""Tests for UK Carbon Intensity source connector."""

from unittest.mock import MagicMock, patch

from pipeline.sources.uk_carbon import UKCarbonSource


def _make_intensity_response():
    """Build a mock carbon intensity response."""
    return {
        "data": [
            {
                "from": "2025-04-07T00:00Z",
                "to": "2025-04-07T00:30Z",
                "intensity": {"forecast": 180, "actual": 175, "index": "moderate"},
            },
            {
                "from": "2025-04-07T00:30Z",
                "to": "2025-04-07T01:00Z",
                "intensity": {"forecast": 190, "actual": 185, "index": "moderate"},
            },
        ]
    }


def _make_generation_response():
    """Build a mock generation mix response."""
    return {
        "data": {
            "from": "2025-04-07T00:00Z",
            "to": "2025-04-08T00:00Z",
            "generationmix": [
                {"fuel": "gas", "perc": 35.0},
                {"fuel": "wind", "perc": 30.0},
                {"fuel": "nuclear", "perc": 15.0},
                {"fuel": "solar", "perc": 8.0},
                {"fuel": "imports", "perc": 7.0},
                {"fuel": "biomass", "perc": 4.0},
                {"fuel": "hydro", "perc": 1.0},
                {"fuel": "coal", "perc": 0.0},
            ],
        }
    }


@patch("pipeline.sources.uk_carbon.get_cached", return_value=None)
@patch("pipeline.sources.uk_carbon.set_cached")
@patch("pipeline.sources.uk_carbon.requests")
def test_fetch_constructs_url_and_caches(mock_requests, mock_set, mock_get):
    """fetch() calls the API and caches the response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": []}
    mock_requests.get.return_value = mock_resp

    source = UKCarbonSource()
    result = source.fetch("/intensity/date/2025-04-07")

    mock_requests.get.assert_called_once()
    assert mock_set.called


@patch("pipeline.sources.uk_carbon.get_cached", return_value={"data": []})
def test_fetch_returns_cached(mock_get):
    """fetch() returns cached response."""
    source = UKCarbonSource()
    result = source.fetch("/intensity/date/2025-04-07")
    assert result == {"data": []}


@patch.object(UKCarbonSource, "fetch", return_value=_make_intensity_response())
def test_get_generation_context_carbon_intensity(mock_fetch):
    """get_generation_context returns carbon intensity for UK."""
    source = UKCarbonSource()
    result = source.get_generation_context(
        "United Kingdom", data_types=["carbon_intensity"]
    )

    assert result["entity"] == "United Kingdom"
    assert result["source"] == "uk_carbon"
    assert "carbon_intensity" in result
    ci = result["carbon_intensity"]
    assert ci["avg_gco2_kwh"] == 180  # (175 + 185) / 2
    assert ci["max_gco2_kwh"] == 185
    assert ci["min_gco2_kwh"] == 175
    assert "generation_mix" not in result


@patch.object(UKCarbonSource, "fetch", return_value=_make_generation_response())
def test_get_generation_context_generation_mix(mock_fetch):
    """get_generation_context returns generation mix for UK."""
    source = UKCarbonSource()
    result = source.get_generation_context(
        "United Kingdom", data_types=["generation_mix"]
    )

    assert "generation_mix" in result
    fuels = {item["fuel"] for item in result["generation_mix"]}
    assert "gas" in fuels
    assert "wind" in fuels
    # Coal at 0% should be excluded
    assert "coal" not in fuels


def test_get_generation_context_non_uk_entity():
    """Non-UK entity returns empty dict."""
    source = UKCarbonSource()
    result = source.get_generation_context("Germany")
    assert result == {}


def test_get_generation_context_uk_aliases():
    """Various UK aliases are accepted."""
    source = UKCarbonSource()
    for alias in ["United Kingdom", "Great Britain", "UK", "GB"]:
        with patch.object(
            UKCarbonSource, "fetch", return_value=_make_intensity_response()
        ):
            result = source.get_generation_context(
                alias, data_types=["carbon_intensity"]
            )
            assert result["entity"] == "United Kingdom", f"Failed for alias: {alias}"
