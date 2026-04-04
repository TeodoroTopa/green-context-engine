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

# US state name → 2-letter abbreviation (EIA uses abbreviations in facets[location])
STATE_ABBREVIATIONS = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
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

    def get_generation_context(self, entity: str, start_date: str = "2020", **kwargs: Any) -> dict[str, Any]:
        """Get electricity generation data for a US entity.

        EIA's electricity endpoints cover US national and state-level data.
        For non-US entities, returns empty generation (Ember covers international).

        Args:
            entity: "United States", a US state name, or "US"
            start_date: Year to start from (default "2020")

        Returns:
            Dict with keys: entity, generation (list of records), source ("eia")
        """
        # Map common names to EIA location codes
        us_names = {"United States", "US", "USA"}
        if entity in us_names:
            return self._fetch_us_generation(entity, "US", start_date)

        # Check if it's a US state (not in COUNTRY_CODES or is "United States")
        if entity not in COUNTRY_CODES or entity == "United States":
            return self._fetch_us_generation(entity, entity, start_date)

        # Non-US country — EIA electricity data is US-only, skip
        logger.debug(f"EIA: skipping non-US entity '{entity}' (Ember covers international)")
        return {"entity": entity, "generation": [], "source": "eia"}

    def _fetch_us_generation(self, entity: str, location: str, start_date: str) -> dict[str, Any]:
        """Fetch US electricity generation by fuel type (national or state)."""
        params = {
            "data[]": "generation",
            "frequency": "annual",
            "start": start_date,
            "facets[sectorid][]": "99",  # All sectors
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": "5000",
        }
        # "US" = national, otherwise filter by state abbreviation
        if location == "US":
            params["facets[location][]"] = "US"
        else:
            abbrev = STATE_ABBREVIATIONS.get(location, location)
            params["facets[location][]"] = abbrev

        raw = self.fetch("electricity/electric-power-operational-data/data", **params)
        records = raw.get("response", {}).get("data", [])

        generation = []
        for r in records:
            generation.append({
                "period": r.get("period"),
                "fuel_type": r.get("fueltypeid", ""),
                "fuel_description": r.get("fuelTypeDescription", ""),
                "value": r.get("generation"),
                "unit": "thousand MWh",
            })

        return {
            "entity": entity,
            "generation": generation,
            "source": "eia",
        }
