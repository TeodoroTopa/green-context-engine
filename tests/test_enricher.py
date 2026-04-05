"""Tests for the enricher with data strategist integration."""

from unittest.mock import MagicMock

from pipeline.analysis.enricher import Enricher, EnrichedStory
from pipeline.monitors.rss_monitor import Story

STORY = Story(
    title="Solar capacity surges in Germany",
    url="https://example.com/solar-germany",
    summary="Germany added 10 GW of solar in 2025, a record year.",
    published="2026-03-30",
    source="mongabay",
    feed_name="mongabay_energy",
)


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


def test_enrich_uses_strategist_and_fetches_data():
    """Enricher calls strategist, fetches from sources, and analyzes."""
    client = MagicMock()
    ember = MagicMock()

    # Call 1: strategist returns fetch plan
    # Call 2: analysis returns summary + angles
    client.messages.create.side_effect = [
        _mock_response('{"fetches": [{"source": "ember", "entity": "Germany", "role": "primary"}, {"source": "ember", "entity": "World", "role": "benchmark"}], "reasoning": "Compare to global"}'),
        _mock_response('{"summary": "Germany solar growing fast.", "angles": ["Record capacity"]}'),
    ]
    ember.get_generation_context.return_value = {
        "entity": "Germany",
        "generation": [{"series": "Solar", "generation_twh": 72, "date": "2025"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 350, "date": "2025"}],
    }

    sources = {"ember": ember}
    enricher = Enricher(sources, client)
    result = enricher.enrich(STORY)

    assert result.entities == ["Germany"]
    assert "Germany" in result.ember_data
    assert "World" in result.benchmark_data
    assert result.fetch_plan["reasoning"] == "Compare to global"
    # 2 Claude calls: strategist + analysis
    assert client.messages.create.call_count == 2


def test_execute_plan_filters_empty_source_data():
    """Sources returning empty data should be excluded from results."""
    client = MagicMock()
    ember = MagicMock()
    gfw = MagicMock()

    # Ember returns real data, GFW returns empty
    ember.get_generation_context.return_value = {
        "entity": "Germany",
        "generation": [{"series": "Solar", "generation_twh": 72, "date": "2025"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 350, "date": "2025"}],
    }
    gfw.get_generation_context.return_value = {
        "entity": "Germany",
        "tree_cover_loss": [],
        "source": "gfw",
    }

    sources = {"ember": ember, "gfw": gfw}
    enricher = Enricher(sources, client)
    plan = {
        "fetches": [
            {"source": "ember", "entity": "Germany", "role": "primary"},
            {"source": "gfw", "entity": "Germany", "role": "primary"},
        ],
        "reasoning": "Test",
    }
    primary, benchmark = enricher._execute_plan(plan)
    # Ember data included, GFW empty data filtered out
    assert "Germany" in primary
    assert primary["Germany"]["generation"][0]["generation_twh"] == 72
    # GFW returned only metadata + empty list, should be filtered
    assert len(primary) == 1


def test_is_empty_data():
    """_is_empty_data correctly identifies empty vs non-empty results."""
    assert Enricher._is_empty_data({}) is True
    assert Enricher._is_empty_data({"entity": "Germany", "source": "gfw"}) is True
    assert Enricher._is_empty_data({"entity": "X", "tree_cover_loss": [], "source": "gfw"}) is True
    assert Enricher._is_empty_data({"entity": "X", "generation": [{"twh": 72}]}) is False
    assert Enricher._is_empty_data({"entity": "X", "total_assessed": 500}) is False


def test_format_primary_data_includes_gfw():
    """_format_primary_data formats GFW tree cover loss data."""
    client = MagicMock()
    sources = {"ember": MagicMock()}
    enricher = Enricher(sources, client)

    data = {
        "Indonesia": {
            "entity": "Indonesia",
            "tree_cover_loss": [
                {"year": 2024, "loss_ha": 1310626.0},
                {"year": 2023, "loss_ha": 1663453.0},
            ],
            "source": "gfw",
        }
    }
    result = enricher._format_primary_data(data)
    assert "Tree cover loss" in result
    assert "2024" in result
    assert "1,310,626" in result
    assert "Indonesia" in result


def test_format_ember_generation():
    """Ember generation data formats correctly (date, series, generation_twh)."""
    client = MagicMock()
    enricher = Enricher({}, client)
    data = {
        "Indonesia": {
            "entity": "Indonesia", "source": "ember",
            "generation": [
                {"date": "2024", "series": "Coal", "generation_twh": 228.43},
                {"date": "2024", "series": "Solar", "generation_twh": 5.2},
            ],
            "carbon_intensity": [{"date": "2024", "emissions_intensity_gco2_per_kwh": 680}],
        }
    }
    result = enricher._format_primary_data(data)
    assert "Ember" in result
    assert "Coal: 228.43 TWh" in result
    assert "Solar: 5.2 TWh" in result
    assert "680 gCO2/kWh" in result


def test_format_eia_generation():
    """EIA generation data formats correctly with whitelist filtering and percentages."""
    client = MagicMock()
    enricher = Enricher({}, client)
    data = {
        "California": {
            "entity": "California", "source": "eia",
            "generation": [
                {"period": "2025", "fuel_type": "ALL", "fuel_description": "all fuels", "value": "205884", "unit": "thousand MWh"},
                {"period": "2025", "fuel_type": "NG", "fuel_description": "natural gas", "value": "73326", "unit": "thousand MWh"},
                {"period": "2025", "fuel_type": "SUN", "fuel_description": "solar", "value": "55574", "unit": "thousand MWh"},
                {"period": "2025", "fuel_type": "DPV", "fuel_description": "small scale solar", "value": "34529", "unit": "thousand MWh"},
                {"period": "2025", "fuel_type": "NUC", "fuel_description": "nuclear", "value": "17558", "unit": "thousand MWh"},
                {"period": "2025", "fuel_type": "AOR", "fuel_description": "all renewables", "value": "87015", "unit": "thousand MWh"},
            ],
        }
    }
    result = enricher._format_primary_data(data)
    assert "EIA" in result
    assert "natural gas: 73.3 TWh (36%)" in result
    assert "utility-scale solar: 55.6 TWh (27%)" in result
    assert "rooftop/small-scale solar: 34.5 TWh (17%)" in result
    assert "nuclear: 17.6 TWh" in result
    assert "all renewables" not in result  # aggregate filtered out
    assert "all fuels" not in result  # aggregate filtered out
    assert "?: ? TWh" not in result  # the old broken format must NOT appear


def test_format_gfw_all_fields():
    """GFW data formats tree cover loss, drivers, and carbon emissions."""
    client = MagicMock()
    enricher = Enricher({}, client)
    data = {
        "Indonesia": {
            "entity": "Indonesia", "source": "gfw",
            "tree_cover_loss": [{"year": 2024, "loss_ha": 1310626.0}],
            "deforestation_drivers": {"Commodity driven deforestation": 57.4, "Forestry": 23.6},
            "carbon_emissions": [{"year": 2024, "co2e_tonnes": 685008830.0}],
        }
    }
    result = enricher._format_primary_data(data)
    assert "1,310,626 hectares" in result
    assert "Commodity driven deforestation: 57.4%" in result
    assert "685.0 million tonnes CO2e" in result


def test_format_noaa_all_fields():
    """NOAA data formats yearly temp, precip, and degree days."""
    client = MagicMock()
    enricher = Enricher({}, client)
    data = {
        "California": {
            "entity": "California", "source": "noaa",
            "yearly_temperature": [{"year": "2023", "type": "TAVG", "value_celsius": 15.5}],
            "yearly_precipitation": [{"year": "2023", "total_mm": 843.4}],
            "heating_degree_days": [{"year": "2023", "value": 1842.8}],
            "cooling_degree_days": [{"year": "2023", "value": 685.4}],
        }
    }
    result = enricher._format_primary_data(data)
    assert "15.5°C" in result
    assert "843.4 mm" in result
    assert "1842.8" in result
    assert "685.4" in result


def test_format_merged_ember_gfw_eia():
    """Merged data from multiple sources for the same entity formats all fields."""
    client = MagicMock()
    enricher = Enricher({}, client)
    # Simulate Ember + GFW merged for Indonesia
    data = {
        "Indonesia": {
            "entity": "Indonesia", "source": "gfw",  # last source to merge wins
            "generation": [{"date": "2024", "series": "Coal", "generation_twh": 228}],
            "carbon_intensity": [{"date": "2024", "emissions_intensity_gco2_per_kwh": 680}],
            "tree_cover_loss": [{"year": 2024, "loss_ha": 1310626.0}],
            "deforestation_drivers": {"Commodity driven deforestation": 57.4},
        }
    }
    result = enricher._format_primary_data(data)
    # Ember fields present (source=gfw but generation fields are Ember-style)
    assert "Coal: 228 TWh" in result
    assert "680 gCO2/kWh" in result
    # GFW fields present
    assert "1,310,626 hectares" in result
    assert "57.4%" in result


def test_enrich_falls_back_on_strategist_failure():
    """Enricher uses default plan when strategist returns bad JSON."""
    client = MagicMock()
    ember = MagicMock()

    client.messages.create.side_effect = [
        _mock_response("not valid json"),  # strategist fails
        _mock_response('{"summary": "World data.", "angles": ["Global trends"]}'),
    ]
    ember.get_generation_context.return_value = {
        "entity": "World",
        "generation": [{"series": "Total", "generation_twh": 29000, "date": "2024"}],
        "carbon_intensity": [{"emissions_intensity_gco2_per_kwh": 471, "date": "2024"}],
    }

    sources = {"ember": ember}
    enricher = Enricher(sources, client)
    result = enricher.enrich(STORY)

    # Falls back to World
    assert "World" in result.ember_data
    assert "Fallback" in result.fetch_plan["reasoning"]
