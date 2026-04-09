"""NLR (National Laboratory of the Rockies, formerly NREL) solar data connector.

Solar Resource Data API: https://developer.nlr.gov/docs/solar/solar-resource-v1/
PVWatts V6 API: https://developer.nlr.gov/docs/solar/pvwatts/v6/

Free API key required (register at developer.nlr.gov).
US-only coverage. Rate limit: 1,000 requests/hour.
"""

import logging
from typing import Any

import requests

from pipeline.sources.base import BaseSource
from pipeline.sources.cache import cache_key, get_cached, set_cached

logger = logging.getLogger(__name__)

BASE_URL = "https://developer.nlr.gov/api"

AVAILABLE_DATA_TYPES = [
    "solar_resource",
    "pvwatts_estimate",
]

# US state capitals + national reference point for lat/lng lookups.
STATE_COORDS = {
    "Alabama": (32.38, -86.30),
    "Alaska": (58.30, -134.42),
    "Arizona": (33.45, -112.07),
    "Arkansas": (34.74, -92.29),
    "California": (38.58, -121.49),
    "Colorado": (39.74, -104.98),
    "Connecticut": (41.76, -72.68),
    "Delaware": (39.16, -75.52),
    "District of Columbia": (38.90, -77.04),
    "Florida": (30.44, -84.28),
    "Georgia": (33.75, -84.39),
    "Hawaii": (21.31, -157.86),
    "Idaho": (43.62, -116.20),
    "Illinois": (39.80, -89.65),
    "Indiana": (39.77, -86.16),
    "Iowa": (41.59, -93.62),
    "Kansas": (39.05, -95.68),
    "Kentucky": (38.20, -84.87),
    "Louisiana": (30.46, -91.19),
    "Maine": (44.31, -69.78),
    "Maryland": (38.97, -76.50),
    "Massachusetts": (42.36, -71.06),
    "Michigan": (42.73, -84.56),
    "Minnesota": (44.96, -93.09),
    "Mississippi": (32.30, -90.18),
    "Missouri": (38.58, -92.17),
    "Montana": (46.60, -112.04),
    "Nebraska": (40.81, -96.68),
    "Nevada": (39.16, -119.77),
    "New Hampshire": (43.21, -71.54),
    "New Jersey": (40.22, -74.76),
    "New Mexico": (35.68, -105.94),
    "New York": (42.65, -73.76),
    "North Carolina": (35.78, -78.64),
    "North Dakota": (46.81, -100.78),
    "Ohio": (39.96, -83.00),
    "Oklahoma": (35.47, -97.52),
    "Oregon": (44.94, -123.03),
    "Pennsylvania": (40.26, -76.88),
    "Puerto Rico": (18.47, -66.12),
    "Rhode Island": (41.82, -71.41),
    "South Carolina": (34.00, -81.03),
    "South Dakota": (44.37, -100.35),
    "Tennessee": (36.17, -86.78),
    "Texas": (30.27, -97.74),
    "Utah": (40.76, -111.89),
    "Vermont": (44.26, -72.58),
    "Virginia": (37.54, -77.43),
    "Washington": (47.04, -122.89),
    "West Virginia": (38.35, -81.63),
    "Wisconsin": (43.07, -89.40),
    "Wyoming": (41.14, -104.82),
    "United States": (39.83, -98.58),  # Geographic center of contiguous US
}


class NLRSource(BaseSource):
    """Fetches US solar resource data and PVWatts estimates from NLR."""

    def __init__(self, api_key: str = ""):
        self._api_key = api_key
        self._cache_ttl = 86400  # Solar resource data is static

    def fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """Fetch data from an NLR API endpoint."""
        url = f"{BASE_URL}{endpoint}"
        params["api_key"] = self._api_key
        key = cache_key(url, params)
        cached = get_cached(key, ttl=self._cache_ttl)
        if cached is not None:
            return cached

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("errors"):
                logger.warning(f"NLR API errors: {data['errors']}")
                return {}
            set_cached(key, data)
            return data
        except requests.RequestException as e:
            logger.warning(f"NLR fetch failed: {e}")
            return {}

    def get_generation_context(self, entity: str, **kwargs: Any) -> dict[str, Any]:
        """Get solar resource data for a US state or the US nationally.

        Args:
            entity: US state name or "United States".
            **kwargs: Optional data_types list.
        """
        coords = STATE_COORDS.get(entity)
        if not coords:
            return {}

        lat, lon = coords
        requested = kwargs.get("data_types") or AVAILABLE_DATA_TYPES
        result = {"entity": entity, "source": "nlr"}

        if "solar_resource" in requested:
            data = self.fetch(
                "/solar/solar_resource/v1.json",
                lat=lat, lon=lon,
            )
            outputs = data.get("outputs", {})
            if outputs:
                solar = {}
                for metric in ("avg_ghi", "avg_dni", "avg_lat_tilt"):
                    values = outputs.get(metric, {})
                    if values:
                        solar[metric] = {
                            "annual": values.get("annual"),
                            "monthly": values.get("monthly", {}),
                        }
                if solar:
                    result["solar_resource"] = solar

        if "pvwatts_estimate" in requested:
            data = self.fetch(
                "/pvwatts/v6.json",
                lat=lat,
                lon=lon,
                system_capacity=1000,  # 1 MW reference system
                module_type=0,         # Standard
                losses=14,             # Industry default
                array_type=0,          # Fixed open rack
                tilt=abs(lat),         # Tilt at latitude
                azimuth=180,           # South-facing
                timeframe="monthly",
            )
            outputs = data.get("outputs", {})
            if outputs:
                result["pvwatts_estimate"] = {
                    "system_capacity_kw": 1000,
                    "ac_annual_kwh": outputs.get("ac_annual"),
                    "capacity_factor_pct": outputs.get("capacity_factor"),
                    "solrad_annual": outputs.get("solrad_annual"),
                    "solrad_monthly": outputs.get("solrad_monthly"),
                    "ac_monthly_kwh": outputs.get("ac_monthly"),
                }
            station = data.get("station_info", {})
            if station:
                result["station_info"] = {
                    "city": station.get("city", ""),
                    "state": station.get("state", ""),
                    "distance_m": station.get("distance"),
                }

        return result
