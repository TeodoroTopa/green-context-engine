"""IUCN Red List API v4 connector — threatened species data by country.

API docs: https://api.iucnredlist.org/api-docs/index.html
Base URL: https://api.iucnredlist.org/api/v4

Key endpoints:
  /countries/           — list all countries (ISO alpha-2)
  /countries/{code}     — all assessments for a country
  /red_list_categories/ — species by threat category

Auth: Bearer token in Authorization header. Register at api.iucnredlist.org.
Data updates 2-3x per year, so cache aggressively (7 day TTL).
"""

import logging
from typing import Any

import requests

from pipeline.sources.base import BaseSource
from pipeline.sources.cache import cache_key, get_cached, set_cached

logger = logging.getLogger(__name__)

BASE_URL = "https://api.iucnredlist.org/api/v4"

# Threat categories in order of severity
THREAT_CATEGORIES = {
    "CR": "Critically Endangered",
    "EN": "Endangered",
    "VU": "Vulnerable",
    "NT": "Near Threatened",
    "LC": "Least Concern",
    "DD": "Data Deficient",
    "EX": "Extinct",
    "EW": "Extinct in the Wild",
}

# ISO alpha-2 codes for countries the pipeline commonly queries
COUNTRY_CODES = {
    "Indonesia": "ID",
    "Brazil": "BR",
    "India": "IN",
    "China": "CN",
    "Colombia": "CO",
    "Mexico": "MX",
    "Australia": "AU",
    "Madagascar": "MG",
    "Peru": "PE",
    "Ecuador": "EC",
    "United States": "US",
    "Malaysia": "MY",
    "Papua New Guinea": "PG",
    "Philippines": "PH",
    "South Africa": "ZA",
    "Tanzania (the United Republic of)": "TZ",
    "Kenya": "KE",
    "Congo (DRC)": "CD",
    "Cameroon": "CM",
    "Myanmar": "MM",
    "Viet Nam": "VN",
    "Thailand": "TH",
    "Nigeria": "NG",
    "Japan": "JP",
    "Germany": "DE",
    "France": "FR",
    "United Kingdom": "GB",
    "Chile": "CL",
    "Argentina": "AR",
    "Bolivia": "BO",
    "Cambodia": "KH",
    "Lao PDR": "LA",
    "Sri Lanka": "LK",
    "New Zealand": "NZ",
    "Costa Rica": "CR",
    "Panama": "PA",
    "Nepal": "NP",
}


class IUCNSource(BaseSource):
    """Connector for the IUCN Red List API v4."""

    def __init__(self, api_key: str | None = None, cache_ttl: int = 604800):
        """Initialize with API token. Default cache TTL is 7 days (data updates 2-3x/year)."""
        self.api_key = api_key
        self.cache_ttl = cache_ttl
        if not self.api_key:
            logger.warning("IUCN_API_KEY not set — IUCN queries will fail")

    def fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """GET an IUCN API endpoint with transparent caching.

        Args:
            endpoint: API path (e.g. "countries/ID")
            **params: Query parameters

        Returns:
            Parsed JSON response.
        """
        url = f"{BASE_URL}/{endpoint}"
        key = cache_key(url, params)

        cached = get_cached(key, self.cache_ttl)
        if cached is not None:
            logger.debug(f"Cache hit for {endpoint}")
            return cached

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        logger.info(f"Fetching IUCN {endpoint}")
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        set_cached(key, data)
        return data

    def get_generation_context(self, entity: str, **kwargs) -> dict[str, Any]:
        """Get threatened species summary for a country.

        Despite the name (inherited from BaseSource), this returns
        biodiversity threat data, not electricity generation.

        Args:
            entity: Country name (e.g. "Indonesia")

        Returns:
            Dict with: entity, threatened_species (dict of category→count),
            total_assessed, source ("iucn")
        """
        iso = COUNTRY_CODES.get(entity)
        if not iso:
            logger.debug(f"IUCN: no country code for '{entity}', skipping")
            return {"entity": entity, "threatened_species": {}, "total_assessed": 0, "source": "iucn"}

        return self._fetch_country_summary(entity, iso)

    def _fetch_country_summary(self, entity: str, iso: str) -> dict[str, Any]:
        """Fetch and summarize threatened species for a country.

        Paginates through country assessments and counts by threat category.
        """
        counts: dict[str, int] = {}
        total = 0
        page = 1

        try:
            while True:
                data = self.fetch(
                    f"countries/{iso}",
                    latest="true",
                    scope_code="1",
                    page=str(page),
                )

                assessments = data.get("assessments", [])
                if not assessments:
                    break

                for a in assessments:
                    category = a.get("red_list_category", {}).get("code", "")
                    if category in THREAT_CATEGORIES:
                        counts[category] = counts.get(category, 0) + 1
                    total += 1

                # Stop if we got fewer than a full page (100 is the max)
                if len(assessments) < 100:
                    break
                page += 1

                # Safety: don't paginate forever
                if page > 50:
                    logger.warning(f"IUCN pagination limit reached for {entity}")
                    break

            return {
                "entity": entity,
                "threatened_species": counts,
                "total_assessed": total,
                "source": "iucn",
            }

        except requests.RequestException as e:
            logger.warning(f"Failed to fetch IUCN data for {entity}: {e}")
            return {"entity": entity, "threatened_species": {}, "total_assessed": 0, "source": "iucn"}
