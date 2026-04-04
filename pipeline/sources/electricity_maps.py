"""Electricity Maps API connector — real-time carbon intensity and power breakdown.

API docs: https://docs.electricitymaps.com/
Signup:   https://app.electricitymaps.com/auth/signup (free tier, no credit card)

Free tier limitations:
  - 1 zone only
  - 50 requests/hour
  - Non-commercial use only

Data: real-time carbon intensity (gCO2eq/kWh) and electricity mix by source type.
Zones use ISO 3166-1 alpha-2 codes (e.g., DE, GB, US-CAL-CISO).
"""

import logging
from typing import Any

import requests

from pipeline.sources.base import BaseSource
from pipeline.sources.cache import cache_key, get_cached, set_cached

logger = logging.getLogger(__name__)

BASE_URL = "https://api.electricitymaps.com"

# Map country/region names to Electricity Maps zone codes
ZONE_CODES = {
    "Germany": "DE",
    "France": "FR",
    "United Kingdom": "GB",
    "Spain": "ES",
    "Italy": "IT",
    "Sweden": "SE",
    "Norway": "NO-NO1",
    "Denmark": "DK-DK1",
    "Netherlands": "NL",
    "Poland": "PL",
    "Austria": "AT",
    "Belgium": "BE",
    "Switzerland": "CH",
    "Portugal": "PT",
    "Finland": "FI",
    "Ireland": "IE",
    "Greece": "GR",
    "Czech Republic": "CZ",
    "Romania": "RO",
    "Hungary": "HU",
    "Japan": "JP-TK",
    "South Korea": "KR",
    "Australia": "AU-NSW",
    "India": "IN-WE",
    "Brazil": "BR-CS",
    "Canada": "CA-ON",
    "United States": "US-CAL-CISO",
    "South Africa": "ZA",
    "New Zealand": "NZ",
    "Taiwan": "TW",
    "Singapore": "SG",
}


class ElectricityMapsSource(BaseSource):
    """Connector for the Electricity Maps API.

    Note: Free tier is limited to 1 zone and 50 requests/hour.
    The connector is built to handle multi-zone queries but will
    fail gracefully on the free tier if a second zone is requested.
    """

    def __init__(self, api_key: str | None = None, cache_ttl: int = 3600):
        self.api_key = api_key
        self.cache_ttl = cache_ttl  # 1 hour default (real-time data)
        if not self.api_key:
            logger.warning("ELECTRICITY_MAPS_API_KEY not set — queries will fail")

    def fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """GET an Electricity Maps API endpoint with transparent caching.

        Args:
            endpoint: API path (e.g. "v3/carbon-intensity/latest")
            **params: Query parameters

        Returns:
            Parsed JSON response.

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        url = f"{BASE_URL}/{endpoint}"
        key = cache_key(url, params)

        cached = get_cached(key, self.cache_ttl)
        if cached is not None:
            logger.debug(f"Cache hit for Electricity Maps {endpoint}")
            return cached

        headers = {"auth-token": self.api_key} if self.api_key else {}

        logger.info(f"Fetching Electricity Maps {endpoint}")
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        set_cached(key, data)
        return data

    def get_generation_context(self, entity: str, **kwargs: Any) -> dict[str, Any]:
        """Get real-time carbon intensity and power breakdown for a zone.

        Args:
            entity: Country or region name (e.g., "Germany", "United Kingdom")

        Returns:
            Dict with keys: entity, carbon_intensity_realtime, power_breakdown,
            datetime, source ("electricity_maps")
        """
        zone = ZONE_CODES.get(entity)
        if not zone:
            logger.debug(f"Electricity Maps: no zone code for '{entity}', skipping")
            return {
                "entity": entity,
                "carbon_intensity_realtime": None,
                "power_breakdown": {},
                "source": "electricity_maps",
            }

        return self._fetch_zone_data(entity, zone)

    def _fetch_zone_data(self, entity: str, zone: str) -> dict[str, Any]:
        """Fetch latest carbon intensity and power breakdown for a zone."""
        carbon_intensity = None
        power_breakdown = {}
        data_datetime = None

        try:
            ci_data = self.fetch("v3/carbon-intensity/latest", zone=zone)
            carbon_intensity = ci_data.get("carbonIntensity")
            data_datetime = ci_data.get("datetime")
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch carbon intensity for {entity}: {e}")

        try:
            pb_data = self.fetch("v3/power-breakdown/latest", zone=zone)
            raw_breakdown = pb_data.get("powerConsumptionBreakdown") or {}
            # Filter out null/zero values for cleaner output
            power_breakdown = {
                k: v for k, v in raw_breakdown.items()
                if v is not None and v > 0
            }
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch power breakdown for {entity}: {e}")

        return {
            "entity": entity,
            "carbon_intensity_realtime": carbon_intensity,
            "power_breakdown": power_breakdown,
            "datetime": data_datetime,
            "source": "electricity_maps",
        }
