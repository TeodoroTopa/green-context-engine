"""EIA Open Data API v2 connector — US and international electricity data.

API docs: https://www.eia.gov/opendata/documentation.php
Base URL: https://api.eia.gov/v2

Key routes used:
  /electricity/electric-power-operational-data/data  — US generation by fuel/state
  /international/data                                — international generation

Auth: api_key query parameter (free — register at eia.gov/opendata/register.php).
Rate limits: ~9,000 req/hour, <5 req/second. Max 5,000 rows per response.
"""

import logging
from typing import Any

import requests

from pipeline.sources.base import BaseSource
from pipeline.sources.cache import cache_key, get_cached, set_cached

logger = logging.getLogger(__name__)

BASE_URL = "https://api.eia.gov/v2"

# ISO-3166 alpha-3 codes for countries the enricher commonly queries.
# EIA international data uses these codes, not country names.
COUNTRY_CODES = {
    "World": "WORL",
    "United States": "USA",
    "China": "CHN",
    "India": "IND",
    "Germany": "DEU",
    "Brazil": "BRA",
    "Indonesia": "IDN",
    "Japan": "JPN",
    "United Kingdom": "GBR",
    "France": "FRA",
    "Australia": "AUS",
    "South Africa": "ZAF",
    "Canada": "CAN",
    "Mexico": "MEX",
    "South Korea": "KOR",
    "Russia": "RUS",
    "Turkey": "TUR",
    "Saudi Arabia": "SAU",
    "Nigeria": "NGA",
    "Vietnam": "VNM",
    "Thailand": "THA",
    "Poland": "POL",
    "Italy": "ITA",
    "Spain": "ESP",
    "Chile": "CHL",
    "Colombia": "COL",
    "Argentina": "ARG",
    "Egypt": "EGY",
    "Kenya": "KEN",
    "Philippines": "PHL",
    "Pakistan": "PAK",
    "Bangladesh": "BGD",
}

# EIA international productId → fuel type label.
# Discoverable via /v2/international/facet/productId, but we hardcode the key ones.
PRODUCT_IDS = {
    "2": "Total electricity",
    "29": "Nuclear",
    "33": "Renewables",
    "35": "Hydroelectricity",
    "36": "Non-hydro renewables",
    "37": "Geothermal",
    "38": "Wind",
    "39": "Solar",
    "40": "Biomass",
    "79": "Coal",
    "80": "Natural gas",
    "81": "Petroleum",
}


class EIASource(BaseSource):
    """Connector for the EIA Open Data API v2."""

    def __init__(self, api_key: str | None = None, cache_ttl: int = 86400):
        self.api_key = api_key
        self.cache_ttl = cache_ttl
        if not self.api_key:
            logger.warning("EIA_API_KEY not set — EIA queries will fail")

    def fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """GET an EIA endpoint with transparent caching.

        Args:
            endpoint: API path, e.g. "electricity/electric-power-operational-data/data"
            **params: Query parameters (facets, data columns, etc.)

        Returns:
            Parsed JSON response.

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        url = f"{BASE_URL}/{endpoint}"
        params["api_key"] = self.api_key
        key = cache_key(url, params)

        cached = get_cached(key, self.cache_ttl)
        if cached is not None:
            logger.debug(f"Cache hit for {endpoint}")
            return cached

        logger.info(f"Fetching EIA {endpoint}")
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        set_cached(key, data)
        return data

    def get_generation_context(self, entity: str, start_date: str = "2020") -> dict[str, Any]:
        """Get electricity generation data for a country or US state.

        For international entities, queries /international/data.
        For US states, queries /electricity/electric-power-operational-data/data.

        Args:
            entity: Country name (e.g. "Germany") or US state name
            start_date: Year to start from (default "2020")

        Returns:
            Dict with keys: entity, generation (list of records), source ("eia")
        """
        country_code = COUNTRY_CODES.get(entity)
        if country_code:
            return self._fetch_international(entity, country_code, start_date)
        # Try as US state
        return self._fetch_us_state(entity, start_date)

    def _fetch_international(self, entity: str, country_code: str, start_date: str) -> dict[str, Any]:
        """Fetch international electricity generation by fuel type."""
        # EIA v2 uses bracket notation for facets/data in query params
        params = {
            "facets[countryRegionId][]": country_code,
            "facets[activityId][]": "1",  # 1 = generation
            "frequency": "annual",
            "start": start_date,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": "5000",
        }
        raw = self.fetch("international/data", **params)
        records = raw.get("response", {}).get("data", [])

        generation = []
        for r in records:
            product_id = str(r.get("productId", ""))
            generation.append({
                "period": r.get("period"),
                "fuel_type": PRODUCT_IDS.get(product_id, r.get("productName", product_id)),
                "value": r.get("value"),
                "unit": r.get("unit"),
            })

        return {
            "entity": entity,
            "generation": generation,
            "source": "eia",
        }

    def _fetch_us_state(self, state: str, start_date: str) -> dict[str, Any]:
        """Fetch US state electricity generation by fuel type."""
        params = {
            "facets[statedescription][]": state,
            "facets[sectorid][]": "99",  # All sectors
            "data[]": "generation",
            "frequency": "annual",
            "start": start_date,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": "5000",
        }
        raw = self.fetch("electricity/electric-power-operational-data/data", **params)
        records = raw.get("response", {}).get("data", [])

        generation = []
        for r in records:
            generation.append({
                "period": r.get("period"),
                "fuel_type": r.get("fueltypeid", ""),
                "fuel_description": r.get("fueltypedescription", ""),
                "value": r.get("generation"),
                "unit": "thousand MWh",
            })

        return {
            "entity": state,
            "generation": generation,
            "source": "eia",
        }
