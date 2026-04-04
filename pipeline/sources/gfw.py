"""Global Forest Watch API connector — tree cover loss and deforestation data.

API docs: https://data-api.globalforestwatch.org/
         https://resource-watch.github.io/doc-api/

Key dataset: umd_tree_cover_loss (University of Maryland, 30m resolution, 2000-2024)

Auth: API key via x-api-key header. Register at globalforestwatch.org.
"""

import logging
from typing import Any

import requests

from pipeline.sources.base import BaseSource
from pipeline.sources.cache import cache_key, get_cached, set_cached

logger = logging.getLogger(__name__)

BASE_URL = "https://data-api.globalforestwatch.org"
DATASET = "umd_tree_cover_loss"
VERSION = "v1.11"

# ISO-3166 alpha-3 codes for GFW country queries
COUNTRY_CODES = {
    "Indonesia": "IDN",
    "Brazil": "BRA",
    "Congo (DRC)": "COD",
    "Malaysia": "MYS",
    "Colombia": "COL",
    "Bolivia": "BOL",
    "Peru": "PER",
    "India": "IND",
    "China": "CHN",
    "Mexico": "MEX",
    "Australia": "AUS",
    "Russia": "RUS",
    "Canada": "CAN",
    "United States": "USA",
    "Argentina": "ARG",
    "Paraguay": "PRY",
    "Myanmar": "MMR",
    "Cambodia": "KHM",
    "Lao PDR": "LAO",
    "Thailand": "THA",
    "Nigeria": "NGA",
    "Cameroon": "CMR",
    "Ghana": "GHA",
    "Cote d'Ivoire": "CIV",
    "Madagascar": "MDG",
    "Mozambique": "MOZ",
    "Tanzania (the United Republic of)": "TZA",
    "Kenya": "KEN",
    "Philippines": "PHL",
    "Viet Nam": "VNM",
    "Papua New Guinea": "PNG",
    "Ecuador": "ECU",
    "Chile": "CHL",
    "South Africa": "ZAF",
    "Germany": "DEU",
    "France": "FRA",
    "United Kingdom": "GBR",
    "Japan": "JPN",
    "South Korea": "KOR",
}


class GFWSource(BaseSource):
    """Connector for the Global Forest Watch Data API."""

    def __init__(self, api_key: str | None = None, cache_ttl: int = 86400):
        self.api_key = api_key
        self.cache_ttl = cache_ttl
        if not self.api_key:
            logger.warning("GFW_API_KEY not set — GFW queries will fail")

    def fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """GET a GFW Data API endpoint with transparent caching.

        Args:
            endpoint: API path (e.g. "dataset/umd_tree_cover_loss/v1.11/query/json")
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
            logger.debug(f"Cache hit for {endpoint}")
            return cached

        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        logger.info(f"Fetching GFW {endpoint}")
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        set_cached(key, data)
        return data

    def get_generation_context(self, entity: str, start_date: str = "2020") -> dict[str, Any]:
        """Get tree cover loss data for a country.

        Despite the name (inherited from BaseSource), this returns
        deforestation data, not electricity generation.

        Args:
            entity: Country name (e.g. "Indonesia", "Brazil")
            start_date: Year to start from (default "2020")

        Returns:
            Dict with keys: entity, tree_cover_loss (list), source ("gfw")
        """
        iso = COUNTRY_CODES.get(entity)
        if not iso:
            logger.debug(f"GFW: no country code for '{entity}', skipping")
            return {"entity": entity, "tree_cover_loss": [], "source": "gfw"}

        return self._fetch_country_loss(entity, iso, start_date)

    def _get_geostore_id(self, iso: str) -> str | None:
        """Get the GFW geostore ID for a country's administrative boundary."""
        url = f"{BASE_URL}/geostore/admin/{iso}"
        key = cache_key(url, {})
        cached = get_cached(key, self.cache_ttl)
        if cached is not None:
            return cached.get("id")

        try:
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            geostore_id = resp.json().get("data", {}).get("id", "")
            if geostore_id:
                set_cached(key, {"id": geostore_id})
            return geostore_id or None
        except requests.RequestException as e:
            logger.warning(f"Failed to get geostore for {iso}: {e}")
            return None

    def _fetch_country_loss(self, entity: str, iso: str, start_date: str) -> dict[str, Any]:
        """Fetch tree cover loss for a country using geostore boundary."""
        geostore_id = self._get_geostore_id(iso)
        if not geostore_id:
            logger.warning(f"No geostore found for {entity} ({iso})")
            return {"entity": entity, "tree_cover_loss": [], "source": "gfw"}

        sql = (
            f"SELECT SUM(umd_tree_cover_loss__ha) as loss_ha, "
            f"umd_tree_cover_loss__year "
            f"FROM data "
            f"GROUP BY umd_tree_cover_loss__year "
            f"ORDER BY umd_tree_cover_loss__year DESC"
        )

        try:
            raw = self.fetch(
                f"dataset/{DATASET}/{VERSION}/query",
                sql=sql,
                geostore_id=geostore_id,
                geostore_origin="gfw",
            )
            records = raw.get("data", [])

            tree_cover_loss = []
            for r in records:
                year = r.get("umd_tree_cover_loss__year")
                loss = r.get("loss_ha")
                if year and int(year) >= int(start_date):
                    tree_cover_loss.append({
                        "year": year,
                        "loss_ha": loss,
                    })

            return {
                "entity": entity,
                "tree_cover_loss": tree_cover_loss,
                "source": "gfw",
            }
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch GFW data for {entity}: {e}")
            return {"entity": entity, "tree_cover_loss": [], "source": "gfw"}
