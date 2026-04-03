"""Ember API connector — electricity generation, carbon intensity, and emissions data.

API docs: https://api.ember-energy.org/v1/docs
Base URL: https://api.ember-energy.org/v1

Key endpoints used:
  /electricity-generation/yearly   — generation by source per country/year
  /electricity-generation/monthly  — same, monthly granularity
  /carbon-intensity/yearly         — CO2 per kWh by country/year
  /carbon-intensity/monthly        — same, monthly granularity

All query params are optional. Responses have shape:
  {"stats": {...}, "data": [{...}, ...]}

No rate limits currently. Auth via optional `api_key` query param.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import requests

from pipeline.sources.base import BaseSource
from pipeline.sources.cache import cache_key, get_cached, set_cached

logger = logging.getLogger(__name__)

BASE_URL = "https://api.ember-energy.org/v1"


class EmberSource(BaseSource):
    """Connector for the Ember Energy API."""

    def __init__(self, api_key: str | None = None, cache_ttl: int = 86400):
        self.api_key = api_key
        self.cache_ttl = cache_ttl

    def fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """GET an Ember endpoint with transparent caching.

        Args:
            endpoint: API path, e.g. "electricity-generation/yearly"
            **params: Query parameters (entity, start_date, etc.)

        Returns:
            Parsed JSON response with "stats" and "data" keys.

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{BASE_URL}/{endpoint}"
        key = cache_key(url, params)

        cached = get_cached(key, self.cache_ttl)
        if cached is not None:
            logger.debug(f"Cache hit for {endpoint}")
            return cached

        logger.info(f"Fetching {endpoint} with params {params}")
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        set_cached(key, data)
        return data

    def get_generation_context(self, entity: str, start_date: str = "2020") -> dict[str, Any]:
        """Get electricity generation mix + carbon intensity for a country.

        This is the main method the enricher calls. It combines two API calls
        to give a full picture of a country's electricity landscape.

        Args:
            entity: Country or region name (e.g. "Germany", "World")
            start_date: Year to start from (default "2020")

        Returns:
            Dict with keys: entity, generation (list), carbon_intensity (list)
        """
        generation = self.fetch(
            "electricity-generation/yearly",
            entity=entity,
            start_date=start_date,
            is_aggregate_series="false",
        )
        carbon = self.fetch(
            "carbon-intensity/yearly",
            entity=entity,
            start_date=start_date,
        )
        return {
            "entity": entity,
            "generation": generation.get("data", []),
            "carbon_intensity": carbon.get("data", []),
        }

    def get_monthly_trend(self, entity: str, months: int = 12) -> dict[str, Any]:
        """Get recent monthly generation data for trend detection.

        Args:
            entity: Country or region name
            months: How many months back to look (default 12)

        Returns:
            Raw API response for monthly electricity generation.
        """
        start = (datetime.now() - timedelta(days=months * 31)).strftime("%Y-%m")
        return self.fetch(
            "electricity-generation/monthly",
            entity=entity,
            start_date=start,
            is_aggregate_series="false",
        )
