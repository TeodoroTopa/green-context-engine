"""UK Carbon Intensity API connector — GB grid carbon intensity and generation mix.

API docs: https://carbon-intensity.github.io/api-definitions/
Free and open, no API key required. CC BY 4.0 license.
Data from National Energy System Operator (NESO).
30-minute resolution, 96+ hour forecasts, 14 DNO regions.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import requests

from pipeline.sources.base import BaseSource
from pipeline.sources.cache import cache_key, get_cached, set_cached

logger = logging.getLogger(__name__)

BASE_URL = "https://api.carbonintensity.org.uk"

AVAILABLE_DATA_TYPES = [
    "carbon_intensity",
    "generation_mix",
    "intensity_trend",
]

# Entities this source can serve
_UK_ALIASES = {"United Kingdom", "Great Britain", "UK", "GB", "England"}


class UKCarbonSource(BaseSource):
    """Fetches carbon intensity and generation mix for Great Britain."""

    def __init__(self):
        self._cache_ttl = 3600  # 1 hour — data updates every 30 min

    def fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """Fetch data from the UK Carbon Intensity API."""
        url = f"{BASE_URL}{endpoint}"
        key = cache_key(url, params)
        cached = get_cached(key, ttl=self._cache_ttl)
        if cached is not None:
            return cached

        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            set_cached(key, data)
            return data
        except requests.RequestException as e:
            logger.warning(f"UK Carbon Intensity fetch failed: {e}")
            return {}

    def get_generation_context(self, entity: str, **kwargs: Any) -> dict[str, Any]:
        """Get carbon intensity and generation mix for the UK.

        Args:
            entity: Must be a UK alias (returns empty for non-UK entities).
            **kwargs: Optional data_types list to fetch selectively.
        """
        if entity not in _UK_ALIASES:
            return {}

        requested = kwargs.get("data_types") or AVAILABLE_DATA_TYPES

        # Fetch yesterday's data (most recent complete day)
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        result = {"entity": "United Kingdom", "date": yesterday, "source": "uk_carbon"}

        if "carbon_intensity" in requested:
            data = self.fetch(f"/intensity/date/{yesterday}")
            periods = data.get("data", [])
            if periods:
                actuals = [
                    p["intensity"]["actual"]
                    for p in periods
                    if p.get("intensity", {}).get("actual") is not None
                ]
                if actuals:
                    result["carbon_intensity"] = {
                        "avg_gco2_kwh": round(sum(actuals) / len(actuals)),
                        "max_gco2_kwh": max(actuals),
                        "min_gco2_kwh": min(actuals),
                        "periods": len(actuals),
                    }

        if "generation_mix" in requested:
            data = self.fetch(f"/generation/{yesterday}/pt24h")
            gen_data = data.get("data", {})
            # Response can be a dict with "generationmix" or a list of periods
            mix = []
            if isinstance(gen_data, dict):
                mix = gen_data.get("generationmix", [])
            elif isinstance(gen_data, list) and gen_data:
                # Average generation mix across all half-hour periods
                fuel_totals: dict[str, list[float]] = {}
                for period in gen_data:
                    for item in period.get("generationmix", []):
                        fuel = item.get("fuel", "")
                        perc = item.get("perc", 0) or 0
                        fuel_totals.setdefault(fuel, []).append(perc)
                mix = [
                    {"fuel": fuel, "perc": round(sum(vals) / len(vals), 1)}
                    for fuel, vals in fuel_totals.items()
                ]
            if mix:
                result["generation_mix"] = [
                    item for item in mix if item.get("perc", 0) > 0
                ]

        if "intensity_trend" in requested:
            week_ago = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%dT00:00Z")
            yesterday_end = f"{yesterday}T23:59Z"
            data = self.fetch(f"/intensity/stats/{week_ago}/{yesterday_end}")
            stats = data.get("data", [])
            if stats and len(stats) > 0:
                entry = stats[0]
                intensity = entry.get("intensity", {})
                if intensity:
                    result["intensity_trend"] = {
                        "period_days": 7,
                        "avg_gco2_kwh": intensity.get("average"),
                        "max_gco2_kwh": intensity.get("max"),
                        "min_gco2_kwh": intensity.get("min"),
                    }

        return result
