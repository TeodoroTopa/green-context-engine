"""Open-Meteo API connector — solar radiation, wind speed, and weather data.

API docs: https://open-meteo.com/en/docs/historical-weather-api
Free for non-commercial use, no API key required.
Global coverage at 10km resolution, historical data back to 1940.
"""

import logging
from datetime import datetime
from typing import Any

import requests

from pipeline.sources.base import BaseSource
from pipeline.sources.cache import cache_key, get_cached, set_cached

logger = logging.getLogger(__name__)

BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

AVAILABLE_DATA_TYPES = [
    "solar_radiation",
    "wind_speed",
    "temperature",
    "precipitation",
]

# Capital city lat/lng for country-level queries.
# Open-Meteo needs coordinates, not country names.
COUNTRY_COORDS = {
    "United States": (38.9, -77.0),
    "China": (39.9, 116.4),
    "India": (28.6, 77.2),
    "Germany": (52.5, 13.4),
    "Japan": (35.7, 139.7),
    "United Kingdom": (51.5, -0.1),
    "France": (48.9, 2.3),
    "Brazil": (-15.8, -47.9),
    "Canada": (45.4, -75.7),
    "Australia": (-35.3, 149.1),
    "South Korea": (37.6, 127.0),
    "Russia": (55.8, 37.6),
    "Italy": (41.9, 12.5),
    "Spain": (40.4, -3.7),
    "Mexico": (19.4, -99.1),
    "Indonesia": (-6.2, 106.8),
    "Saudi Arabia": (24.7, 46.7),
    "Nigeria": (9.1, 7.5),
    "South Africa": (-25.7, 28.2),
    "Colombia": (4.7, -74.1),
    "Argentina": (-34.6, -58.4),
    "Chile": (-33.4, -70.6),
    "Norway": (59.9, 10.8),
    "Sweden": (59.3, 18.1),
    "Thailand": (13.8, 100.5),
    "Viet Nam": (21.0, 105.9),
    "Philippines": (14.6, 121.0),
    "Egypt": (30.0, 31.2),
    "Kenya": (-1.3, 36.8),
    "Greece": (37.98, 23.73),
    "Turkey": (39.9, 32.9),
    "Poland": (52.2, 21.0),
    "Netherlands": (52.4, 4.9),
    "Portugal": (38.7, -9.1),
    "Morocco": (33.97, -6.85),
    "Pakistan": (33.7, 73.0),
    "Bangladesh": (23.8, 90.4),
    "Malaysia": (3.1, 101.7),
    "Peru": (-12.0, -77.0),
    "Puerto Rico": (18.47, -66.12),
}

# Daily variables grouped by data_type
_VARIABLES = {
    "solar_radiation": ["shortwave_radiation_sum"],
    "wind_speed": ["wind_speed_10m_max", "wind_speed_10m_mean"],
    "temperature": ["temperature_2m_mean", "temperature_2m_max", "temperature_2m_min"],
    "precipitation": ["precipitation_sum"],
}


class OpenMeteoSource(BaseSource):
    """Fetches weather and solar resource data from Open-Meteo."""

    def __init__(self):
        self._cache_ttl = 86400

    def fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """Fetch data from Open-Meteo archive API."""
        url = endpoint  # Open-Meteo uses a single endpoint with params
        key = cache_key(url, params)
        cached = get_cached(key, ttl=self._cache_ttl)
        if cached is not None:
            return cached

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            set_cached(key, data)
            return data
        except requests.RequestException as e:
            logger.warning(f"Open-Meteo fetch failed: {e}")
            return {}

    def get_generation_context(self, entity: str, **kwargs: Any) -> dict[str, Any]:
        """Get solar/wind/weather data for a country.

        Args:
            entity: Country name.
            **kwargs: Optional data_types list to fetch selectively.
        """
        coords = COUNTRY_COORDS.get(entity)
        if not coords:
            logger.debug(f"No coordinates for entity: {entity}")
            return {}

        lat, lng = coords
        requested = kwargs.get("data_types") or AVAILABLE_DATA_TYPES

        # Build variable list from requested data types
        variables = []
        for dt in requested:
            variables.extend(_VARIABLES.get(dt, []))
        if not variables:
            return {}

        # Fetch last full calendar year
        last_year = datetime.now().year - 1
        params = {
            "latitude": lat,
            "longitude": lng,
            "start_date": f"{last_year}-01-01",
            "end_date": f"{last_year}-12-31",
            "daily": ",".join(variables),
            "timezone": "auto",
        }

        data = self.fetch(BASE_URL, **params)
        if not data or "daily" not in data:
            return {}

        daily = data["daily"]
        result = {"entity": entity, "year": last_year, "source": "openmeteo"}

        if "solar_radiation" in requested and "shortwave_radiation_sum" in daily:
            values = [v for v in daily["shortwave_radiation_sum"] if v is not None]
            if values:
                # Convert from MJ/m2 (daily sum) to kWh/m2/day
                avg_mj = sum(values) / len(values)
                avg_kwh = avg_mj / 3.6
                result["solar_radiation"] = {
                    "avg_daily_kwh_m2": round(avg_kwh, 2),
                    "avg_daily_mj_m2": round(avg_mj, 2),
                    "days_measured": len(values),
                }

        if "wind_speed" in requested:
            if "wind_speed_10m_mean" in daily:
                values = [v for v in daily["wind_speed_10m_mean"] if v is not None]
                if values:
                    result["wind_speed"] = {
                        "avg_10m_kmh": round(sum(values) / len(values), 1),
                        "days_measured": len(values),
                    }
            if "wind_speed_10m_max" in daily:
                maxes = [v for v in daily["wind_speed_10m_max"] if v is not None]
                if maxes and "wind_speed" in result:
                    result["wind_speed"]["max_10m_kmh"] = round(max(maxes), 1)

        if "temperature" in requested and "temperature_2m_mean" in daily:
            values = [v for v in daily["temperature_2m_mean"] if v is not None]
            if values:
                result["temperature"] = {
                    "avg_c": round(sum(values) / len(values), 1),
                    "days_measured": len(values),
                }
            if "temperature_2m_max" in daily:
                maxes = [v for v in daily["temperature_2m_max"] if v is not None]
                if maxes:
                    result.setdefault("temperature", {})["max_c"] = round(max(maxes), 1)

        if "precipitation" in requested and "precipitation_sum" in daily:
            values = [v for v in daily["precipitation_sum"] if v is not None]
            if values:
                result["precipitation"] = {
                    "total_mm": round(sum(values), 1),
                    "days_measured": len(values),
                }

        return result
