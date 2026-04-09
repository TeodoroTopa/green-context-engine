"""Enricher — connects news stories to energy data via the data strategist.

Flow: Story → strategist picks data to fetch → fetch from multiple sources
→ format data with benchmarks → EnrichedStory ready for drafting.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.analysis.catalog import load_catalog, get_available_sources
from pipeline.analysis.data_strategist import plan_data_fetch
from pipeline.analysis.utils import strip_code_fences
from pipeline.monitors.rss_monitor import Story
from pipeline.sources.base import BaseSource
from pipeline.sources.ember import EmberSource
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

COUNTRIES_FILE = Path("data/reference/countries.json")

# Non-overlapping EIA fuel types to display, with clean names for the writing agent.
# EIA has dozens of overlapping codes (ALL, AOR, COW, FOS, REN, TSN, etc.).
# This whitelist picks one code per real fuel category to avoid double-counting.
_EIA_FUEL_DISPLAY = {
    "NG":  "natural gas",
    "SUN": "utility-scale solar",
    "DPV": "rooftop/small-scale solar",
    "NUC": "nuclear",
    "WND": "wind",
    "HYC": "hydroelectric",
    "GEO": "geothermal",
    "BIO": "biomass",
    "COL": "coal",
    "DFO": "oil",
    "OOG": "other gases",
}


def _format_ember_generation(gen: list[dict]) -> list[str]:
    """Format Ember-style generation data (date, series, generation_twh)."""
    if not gen:
        return []
    latest_year = max(r.get("date", "") for r in gen)
    latest = [r for r in gen if r.get("date") == latest_year]
    lines = [f"Electricity generation mix ({latest_year}, Ember):"]
    for r in sorted(latest, key=lambda x: x.get("generation_twh", 0), reverse=True):
        lines.append(f"  {r.get('series', '?')}: {r.get('generation_twh', '?')} TWh")
    return lines


def _format_eia_generation(gen: list[dict]) -> list[str]:
    """Format EIA-style generation data (period, fuel_description, value in thousand MWh).

    Uses a whitelist of non-overlapping fuel types to avoid double-counting.
    Converts thousand MWh to TWh for consistency with Ember formatting.
    Shows percentage of total generation alongside TWh.
    """
    if not gen:
        return []
    latest_year = max(r.get("period", "") for r in gen)
    latest = [r for r in gen if r.get("period") == latest_year]

    # Get total for percentage calculation
    total_rec = next((r for r in latest if r.get("fuel_type") == "ALL"), None)
    total_twh = float(total_rec["value"]) / 1000 if total_rec else 0

    # Filter to whitelisted fuel types only
    display = [r for r in latest if r.get("fuel_type") in _EIA_FUEL_DISPLAY]
    if not display:
        return []

    lines = [f"Electricity generation mix ({latest_year}, EIA):"]
    for r in sorted(display, key=lambda x: float(x.get("value", 0) or 0), reverse=True):
        val = float(r.get("value", 0) or 0)
        twh = val / 1000
        if twh < 0.1:
            continue
        name = _EIA_FUEL_DISPLAY.get(r["fuel_type"], r.get("fuel_description", "?"))
        pct = f" ({twh / total_twh * 100:.0f}%)" if total_twh > 0 else ""
        lines.append(f"  {name}: {twh:.1f} TWh{pct}")
    return lines


@dataclass
class EnrichedStory:
    """A story with attached data context and analysis."""

    story: Story
    entities: list[str]
    ember_data: dict
    data_summary: str
    suggested_angles: list[str] = field(default_factory=list)
    fetch_plan: dict = field(default_factory=dict)
    benchmark_data: dict = field(default_factory=dict)
    data_text: str = ""


class Enricher:
    """Enriches stories with energy data using AI-driven data selection."""

    def __init__(self, sources: dict[str, BaseSource], client, model: str = "claude-opus-4-6"):
        self.sources = sources  # {"ember": EmberSource, "eia": EIASource, ...}
        self.client = client
        self.model = model
        self._countries = self._load_countries()
        self._catalog_text = load_catalog()

    def _load_countries(self) -> dict[str, str]:
        """Load country name → canonical name mapping."""
        if COUNTRIES_FILE.exists():
            return json.loads(COUNTRIES_FILE.read_text(encoding="utf-8"))
        logger.warning(f"Countries file not found: {COUNTRIES_FILE}")
        return {}

    def enrich(self, story: Story, tracker: UsageTracker | None = None) -> EnrichedStory:
        """Full enrichment pipeline for a single story."""
        # 1. Strategist decides what data to fetch
        fetch_plan = plan_data_fetch(
            self.client, self.model, story, self._catalog_text, tracker,
        )

        # 2. Execute the fetch plan
        primary_data, benchmark_data = self._execute_plan(fetch_plan)

        # 3. Build entities list from primary fetches
        entities = [f["entity"] for f in fetch_plan["fetches"] if f["role"] == "primary"]
        if not entities:
            entities = self._extract_entities_local(story) or ["World"]

        # 4. Format data (drafter interprets it directly — no separate analyzer call)
        data_text = ""
        if primary_data:
            data_text = self._format_primary_data(primary_data)
            if benchmark_data:
                data_text += "\n\n" + self._format_benchmark_data(
                    benchmark_data, fetch_plan.get("reasoning", "")
                )

        return EnrichedStory(
            story=story,
            entities=entities,
            ember_data=primary_data,
            data_summary=data_text,
            suggested_angles=[],
            fetch_plan=fetch_plan,
            benchmark_data=benchmark_data,
            data_text=data_text,
        )

    def _execute_plan(self, plan: dict) -> tuple[dict, dict]:
        """Execute the strategist's fetch plan, dispatching to the right source.

        Fetches run in parallel (ThreadPoolExecutor) since each is an independent
        API call. When multiple sources return data for the same entity, results
        are merged so the drafter sees a combined view.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        primary_data = {}
        benchmark_data = {}

        def _fetch_one(fetch: dict):
            source_name = fetch.get("source", "ember")
            entity = fetch.get("entity", "")
            role = fetch.get("role", "primary")
            data_types = fetch.get("data_types")

            source = self.sources.get(source_name)
            if not source:
                logger.warning(f"Source '{source_name}' not available, skipping {entity}")
                return None
            try:
                data = source.get_generation_context(entity, data_types=data_types)
                if self._is_empty_data(data):
                    logger.debug(f"Empty data from {source_name}/{entity}, skipping")
                    return None
                return (entity, role, data)
            except Exception as e:
                logger.warning(f"Failed to fetch {source_name}/{entity}: {e}")
                return None

        fetches = plan.get("fetches", [])
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_fetch_one, f): f for f in fetches}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    entity, role, data = result
                    target = primary_data if role == "primary" else benchmark_data
                    if entity in target:
                        target[entity].update(data)
                    else:
                        target[entity] = data

        return primary_data, benchmark_data

    @staticmethod
    def _is_empty_data(data: dict) -> bool:
        """Check if a source returned no meaningful data."""
        if not data:
            return True
        # Check if all list/dict values are empty
        for key, value in data.items():
            if key in ("entity", "source"):
                continue  # metadata fields, not data
            if isinstance(value, (list, dict)) and len(value) > 0:
                return False
            if isinstance(value, (int, float)) and value != 0:
                return False
            if isinstance(value, str) and value:
                return False
        return True

    def _extract_entities_local(self, story: Story) -> list[str]:
        """Extract country/region names using local lookup. No API call."""
        text = f"{story.title} {story.summary}"
        found = []
        for name, canonical in self._countries.items():
            if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
                if canonical not in found:
                    found.append(canonical)
        return found

    def _analyze(self, story: Story, data_text: str, tracker: UsageTracker | None = None) -> tuple[str, list[str]]:
        """Claude analyzes the story in context of the energy data."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    "Given this story and data, return JSON with:\n"
                    "1. \"summary\": what the data shows in context of the story (2-3 sentences)\n"
                    "2. \"angles\": 2-3 angles for a brief that connects the story to the data\n\n"
                    "Focus on cross-source connections — what insight emerges from combining "
                    "different data sources that neither provides alone?\n\n"
                    f"<story>\n{story.title}\n{story.summary}\n</story>\n\n"
                    f"<data>\n{data_text}\n</data>"
                ),
            }],
        )
        if tracker:
            tracker.track(response, "analysis")
        text = strip_code_fences(response.content[0].text)
        try:
            result = json.loads(text)
            return result.get("summary", ""), result.get("angles", [])
        except json.JSONDecodeError:
            logger.warning(f"Could not parse analysis: {text[:200]}")
            return text, []

    def _format_primary_data(self, data: dict) -> str:
        """Format primary entity data for the prompt."""
        if not data:
            return ""
        parts = []
        for entity, context in data.items():
            lines = [f"### {entity} (primary)"]
            gen = context.get("generation", [])
            if gen:
                source_id = context.get("source", "")
                if source_id == "eia":
                    lines.extend(_format_eia_generation(gen))
                else:
                    lines.extend(_format_ember_generation(gen))

            carbon = context.get("carbon_intensity", [])
            if carbon:
                latest_c = max(carbon, key=lambda x: x["date"])
                lines.append(
                    f"Carbon intensity ({latest_c['date']}): "
                    f"{latest_c.get('emissions_intensity_gco2_per_kwh', '?')} gCO2/kWh"
                )

            # GFW: tree cover loss
            loss = context.get("tree_cover_loss", [])
            if loss:
                lines.append("Tree cover loss (GFW):")
                for r in loss[:5]:
                    lines.append(f"  {r['year']}: {r['loss_ha']:,.0f} hectares")

            # GFW: deforestation drivers
            drivers = context.get("deforestation_drivers", {})
            if drivers:
                lines.append("Deforestation drivers (GFW, cumulative %):")
                for driver, pct in sorted(drivers.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"  {driver}: {pct}%")

            # GFW: carbon emissions from forest loss
            carbon_e = context.get("carbon_emissions", [])
            if carbon_e:
                lines.append("Forest carbon emissions (GFW):")
                for r in carbon_e[:5]:
                    tonnes = r["co2e_tonnes"]
                    if tonnes >= 1e9:
                        lines.append(f"  {r['year']}: {tonnes/1e9:.2f} billion tonnes CO2e")
                    elif tonnes >= 1e6:
                        lines.append(f"  {r['year']}: {tonnes/1e6:.1f} million tonnes CO2e")
                    else:
                        lines.append(f"  {r['year']}: {tonnes:,.0f} tonnes CO2e")

            # IUCN: threatened species
            species = context.get("threatened_species", {})
            if species:
                lines.append("Threatened species (IUCN):")
                for category, count in species.items():
                    if count > 0:
                        lines.append(f"  {category}: {count}")
                total = context.get("total_assessed", 0)
                if total:
                    lines.append(f"  Total assessed: {total}")

            # NOAA: yearly summaries
            yearly_temp = context.get("yearly_temperature", [])
            if yearly_temp:
                lines.append("Yearly temperature (NOAA):")
                for r in yearly_temp[:9]:
                    lines.append(f"  {r['year']} {r['type']}: {r['value_celsius']}°C")
            yearly_precip = context.get("yearly_precipitation", [])
            if yearly_precip:
                lines.append("Yearly precipitation (NOAA):")
                for r in yearly_precip[:3]:
                    lines.append(f"  {r['year']}: {r['total_mm']} mm")
            hdd = context.get("heating_degree_days", [])
            if hdd:
                lines.append("Heating degree days (NOAA):")
                for r in hdd[:3]:
                    lines.append(f"  {r['year']}: {r['value']}")
            cdd = context.get("cooling_degree_days", [])
            if cdd:
                lines.append("Cooling degree days (NOAA):")
                for r in cdd[:3]:
                    lines.append(f"  {r['year']}: {r['value']}")

            # NOAA: monthly data (fallback)
            temp = context.get("temperature", [])
            if temp and isinstance(temp, list):
                lines.append("Monthly temperature (NOAA):")
                for r in temp[:6]:
                    lines.append(f"  {r['date']} {r['type']}: {r['value_celsius']}°C")
            precip = context.get("precipitation", [])
            if precip and isinstance(precip, list):
                lines.append("Monthly precipitation (NOAA):")
                for r in precip[:6]:
                    lines.append(f"  {r['date']}: {r['value_mm']} mm")

            # NLR: solar resource data (US)
            nlr_solar = context.get("solar_resource", {})
            if nlr_solar and isinstance(nlr_solar, dict) and "avg_ghi" in nlr_solar:
                ghi = nlr_solar["avg_ghi"].get("annual", "?")
                dni = nlr_solar["avg_dni"].get("annual", "?")
                tilt = nlr_solar["avg_lat_tilt"].get("annual", "?")
                lines.append(
                    f"Solar resource (NLR): GHI {ghi} kWh/m²/day, "
                    f"DNI {dni} kWh/m²/day, tilt-at-latitude {tilt} kWh/m²/day"
                )

            # NLR: PVWatts production estimate (US)
            pvwatts = context.get("pvwatts_estimate", {})
            if pvwatts and isinstance(pvwatts, dict) and "ac_annual_kwh" in pvwatts:
                annual_mwh = pvwatts["ac_annual_kwh"] / 1000
                cf = pvwatts.get("capacity_factor_pct", "?")
                lines.append(
                    f"PVWatts estimate for 1 MW reference system (NLR): "
                    f"{annual_mwh:,.0f} MWh/year, {cf}% capacity factor"
                )

            # Open-Meteo: solar radiation
            solar = context.get("solar_radiation", {})
            if solar and isinstance(solar, dict) and "avg_daily_ghi_kwh_m2" in solar:
                year = context.get("year", "")
                ghi = solar.get("avg_daily_ghi_kwh_m2", "?")
                lines.append(f"Solar resource GHI ({year}, Open-Meteo): {ghi} kWh/m²/day average")
                sun_hrs = solar.get("avg_sunshine_hours")
                if sun_hrs:
                    lines.append(f"Average sunshine: {sun_hrs} hours/day ({year}, Open-Meteo)")

            # Open-Meteo: wind speed
            wind = context.get("wind_speed", {})
            if wind and isinstance(wind, dict) and "avg_10m_kmh" in wind:
                year = context.get("year", "")
                avg_10 = wind.get("avg_10m_kmh")
                max_10 = wind.get("max_10m_kmh")
                max_str = f", max gust {max_10} km/h" if max_10 else ""
                lines.append(f"Wind speed at 10m ({year}, Open-Meteo): {avg_10} km/h average{max_str}")

            # Open-Meteo: temperature (dict format, not NOAA list format)
            om_temp = context.get("temperature", {})
            if om_temp and isinstance(om_temp, dict) and "avg_c" in om_temp:
                year = context.get("year", "")
                lines.append(f"Average temperature ({year}, Open-Meteo): {om_temp['avg_c']}°C")

            # Open-Meteo: precipitation (dict format)
            om_precip = context.get("precipitation", {})
            if om_precip and isinstance(om_precip, dict) and "total_mm" in om_precip:
                year = context.get("year", "")
                lines.append(f"Annual precipitation ({year}, Open-Meteo): {om_precip['total_mm']} mm")

            # Open-Meteo: evapotranspiration
            et = context.get("evapotranspiration", {})
            if et and isinstance(et, dict):
                year = context.get("year", "")
                total = et.get("total_mm", "?")
                avg = et.get("avg_daily_mm", "?")
                lines.append(
                    f"Reference evapotranspiration ({year}, Open-Meteo): "
                    f"{total} mm/year ({avg} mm/day avg)"
                )

            # UK Carbon Intensity: daily carbon intensity
            uk_ci = context.get("carbon_intensity", {})
            if uk_ci and isinstance(uk_ci, dict) and "avg_gco2_kwh" in uk_ci:
                date = context.get("date", "")
                lines.append(
                    f"UK grid carbon intensity ({date}, UK Carbon Intensity API): "
                    f"{uk_ci['avg_gco2_kwh']} gCO2/kWh avg, "
                    f"{uk_ci['min_gco2_kwh']}-{uk_ci['max_gco2_kwh']} range"
                )

            # UK Carbon Intensity: generation mix
            uk_mix = context.get("generation_mix", [])
            if uk_mix and isinstance(uk_mix, list) and uk_mix and isinstance(uk_mix[0], dict) and "fuel" in uk_mix[0]:
                date = context.get("date", "")
                lines.append(f"UK generation mix ({date}, UK Carbon Intensity API):")
                for item in sorted(uk_mix, key=lambda x: x.get("perc", 0), reverse=True):
                    lines.append(f"  {item['fuel']}: {item['perc']}%")

            # UK Carbon Intensity: 7-day trend
            trend = context.get("intensity_trend", {})
            if trend and isinstance(trend, dict) and "avg_gco2_kwh" in trend:
                days = trend.get("period_days", 7)
                lines.append(
                    f"UK carbon intensity {days}-day trend (UK Carbon Intensity API): "
                    f"avg {trend['avg_gco2_kwh']} gCO2/kWh, "
                    f"range {trend['min_gco2_kwh']}-{trend['max_gco2_kwh']}"
                )

            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    def _format_benchmark_data(self, data: dict, reasoning: str) -> str:
        """Format benchmark/comparison data for the prompt."""
        lines = ["### Comparison Benchmarks"]
        if reasoning:
            lines.append(f"Context: {reasoning}")
        for entity, context in data.items():
            carbon = context.get("carbon_intensity", [])
            if carbon:
                latest_c = max(carbon, key=lambda x: x["date"])
                ci = latest_c.get("emissions_intensity_gco2_per_kwh", "?")
                lines.append(f"  {entity}: {ci} gCO2/kWh ({latest_c['date']})")
            gen = context.get("generation", [])
            if gen:
                source_id = context.get("source", "")
                if source_id == "eia":
                    lines.extend(f"  {l}" for l in _format_eia_generation(gen))
                else:
                    # Ember: show total generation for benchmarks
                    latest_year = max(r.get("date", "") for r in gen)
                    total = sum(
                        r.get("generation_twh", 0) for r in gen
                        if r.get("date") == latest_year and isinstance(r.get("generation_twh"), (int, float))
                    )
                    if total > 0:
                        lines.append(f"  {entity} total generation ({latest_year}): {total:.0f} TWh")
        return "\n".join(lines)
