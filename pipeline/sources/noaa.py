"""NOAA Climate Data Online (CDO) API connector — temperature and precipitation data.

API docs: https://www.ncdc.noaa.gov/cdo-web/webservices/v2
Token:    https://www.ncdc.noaa.gov/cdo-web/token (free, instant via email)

Primary dataset: GHCND (Global Historical Climatology Network - Daily)
  - 100,000+ stations across 180 countries
  - Daily temperature, precipitation, snowfall
  - Records dating back decades

Rate limits: 5 requests/second, 10,000 requests/day
Query limits: 1-year max date range for daily data, 10-year for monthly/annual
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import requests

from pipeline.sources.base import BaseSource
from pipeline.sources.cache import cache_key, get_cached, set_cached

logger = logging.getLogger(__name__)

BASE_URL = "https://www.ncei.noaa.gov/cdo-web/api/v2"

# FIPS country codes for NOAA location queries (FIPS:XX format)
# See: https://www.ncdc.noaa.gov/cdo-web/webservices/v2#locations
COUNTRY_FIPS = {
    "United States": "FIPS:US",
    "China": "FIPS:CH",
    "India": "FIPS:IN",
    "Germany": "FIPS:GM",
    "United Kingdom": "FIPS:UK",
    "France": "FIPS:FR",
    "Japan": "FIPS:JA",
    "Brazil": "FIPS:BR",
    "Australia": "FIPS:AS",
    "Canada": "FIPS:CA",
    "Russia": "FIPS:RS",
    "South Korea": "FIPS:KS",
    "Indonesia": "FIPS:ID",
    "Mexico": "FIPS:MX",
    "South Africa": "FIPS:SF",
    "Nigeria": "FIPS:NI",
    "Kenya": "FIPS:KE",
    "Colombia": "FIPS:CO",
    "Argentina": "FIPS:AR",
    "Chile": "FIPS:CI",
    "Italy": "FIPS:IT",
    "Spain": "FIPS:SP",
    "Sweden": "FIPS:SW",
    "Norway": "FIPS:NO",
    "Thailand": "FIPS:TH",
    "Viet Nam": "FIPS:VM",
    "Philippines": "FIPS:RP",
    "Egypt": "FIPS:EG",
    "Saudi Arabia": "FIPS:SA",
}

# US state FIPS codes for state-level queries
US_STATE_FIPS = {
    "Alabama": "FIPS:01", "Alaska": "FIPS:02", "Arizona": "FIPS:04",
    "Arkansas": "FIPS:05", "California": "FIPS:06", "Colorado": "FIPS:08",
    "Connecticut": "FIPS:09", "Delaware": "FIPS:10", "Florida": "FIPS:12",
    "Georgia": "FIPS:13", "Hawaii": "FIPS:15", "Idaho": "FIPS:16",
    "Illinois": "FIPS:17", "Indiana": "FIPS:18", "Iowa": "FIPS:19",
    "Kansas": "FIPS:20", "Kentucky": "FIPS:21", "Louisiana": "FIPS:22",
    "Maine": "FIPS:23", "Maryland": "FIPS:24", "Massachusetts": "FIPS:25",
    "Michigan": "FIPS:26", "Minnesota": "FIPS:27", "Mississippi": "FIPS:28",
    "Missouri": "FIPS:29", "Montana": "FIPS:30", "Nebraska": "FIPS:31",
    "Nevada": "FIPS:32", "New Hampshire": "FIPS:33", "New Jersey": "FIPS:34",
    "New Mexico": "FIPS:35", "New York": "FIPS:36", "North Carolina": "FIPS:37",
    "North Dakota": "FIPS:38", "Ohio": "FIPS:39", "Oklahoma": "FIPS:40",
    "Oregon": "FIPS:41", "Pennsylvania": "FIPS:42", "Rhode Island": "FIPS:44",
    "South Carolina": "FIPS:45", "South Dakota": "FIPS:46", "Tennessee": "FIPS:47",
    "Texas": "FIPS:48", "Utah": "FIPS:49", "Vermont": "FIPS:50",
    "Virginia": "FIPS:51", "Washington": "FIPS:53", "West Virginia": "FIPS:54",
    "Wisconsin": "FIPS:55", "Wyoming": "FIPS:56",
}


class NOAASource(BaseSource):
    """Connector for the NOAA Climate Data Online API v2."""

    def __init__(self, api_key: str | None = None, cache_ttl: int = 86400):
        self.api_key = api_key
        self.cache_ttl = cache_ttl
        if not self.api_key:
            logger.warning("NOAA_API_KEY not set — NOAA queries will fail")

    def fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """GET a NOAA CDO API v2 endpoint with transparent caching.

        Args:
            endpoint: API path (e.g. "data", "stations")
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
            logger.debug(f"Cache hit for NOAA {endpoint}")
            return cached

        headers = {"token": self.api_key} if self.api_key else {}

        logger.info(f"Fetching NOAA {endpoint}")
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        set_cached(key, data)
        return data

    # Data types the strategist can request selectively
    AVAILABLE_DATA_TYPES = [
        "yearly_temperature", "yearly_precipitation",
        "heating_degree_days", "cooling_degree_days",
        "monthly_temperature", "monthly_precipitation",
    ]

    def get_generation_context(self, entity: str, **kwargs: Any) -> dict[str, Any]:
        """Get climate data for a country or US state.

        Despite the name (inherited from BaseSource), this returns climate
        data (temperature, precipitation, degree days), not electricity generation.

        Args:
            entity: Country name or US state name
            **kwargs:
                data_types: Optional list of specific data to fetch. Options:
                    "yearly_temperature", "yearly_precipitation",
                    "heating_degree_days", "cooling_degree_days",
                    "monthly_temperature", "monthly_precipitation"
                    If None, fetches yearly data + degree days by default.
                start_date: YYYY string (default: 3 years ago)

        Returns:
            Dict with entity, requested data fields, and source ("noaa").
        """
        location_id = US_STATE_FIPS.get(entity) or COUNTRY_FIPS.get(entity)
        if not location_id:
            logger.debug(f"NOAA: no FIPS code for '{entity}', skipping")
            return {"entity": entity, "source": "noaa"}

        start_date = kwargs.get("start_date", "")
        if not start_date:
            start_date = str(datetime.now().year - 3)

        data_types = kwargs.get("data_types") or [
            "yearly_temperature", "yearly_precipitation",
            "heating_degree_days", "cooling_degree_days",
        ]

        result = {"entity": entity, "source": "noaa"}

        # Determine which datasets/datatypes to query
        yearly_types = [t for t in data_types if t.startswith("yearly_") or t.endswith("_degree_days")]
        monthly_types = [t for t in data_types if t.startswith("monthly_")]

        if yearly_types:
            yearly = self._fetch_yearly(entity, location_id, start_date, yearly_types)
            result.update(yearly)

        if monthly_types:
            monthly = self._fetch_monthly(entity, location_id, start_date, monthly_types)
            result.update(monthly)

        return result

    def _fetch_yearly(
        self, entity: str, location_id: str, start_year: str, data_types: list[str],
    ) -> dict[str, Any]:
        """Fetch yearly summaries from GSOY dataset."""
        end_date = f"{datetime.now().year}-01-01"
        start_date = f"{start_year}-01-01"

        # Build datatype list based on what's requested
        noaa_types = []
        if "yearly_temperature" in data_types:
            noaa_types.extend(["TAVG", "TMAX", "TMIN"])
        if "yearly_precipitation" in data_types:
            noaa_types.append("PRCP")
        if "heating_degree_days" in data_types:
            noaa_types.append("HTDD")
        if "cooling_degree_days" in data_types:
            noaa_types.append("CLDD")

        if not noaa_types:
            return {}

        result = {}
        try:
            raw = self.fetch(
                "data",
                datasetid="GSOY",
                locationid=location_id,
                datatypeid=",".join(noaa_types),
                startdate=start_date,
                enddate=end_date,
                units="metric",
                limit=1000,
            )
            aggregated = self._aggregate_stations(raw.get("results", []), yearly=True)

            if "yearly_temperature" in data_types:
                result["yearly_temperature"] = [
                    {"year": k[0], "type": k[1], "value_celsius": v}
                    for k, v in aggregated.items() if k[1] in ("TAVG", "TMAX", "TMIN")
                ]
            if "yearly_precipitation" in data_types:
                result["yearly_precipitation"] = [
                    {"year": k[0], "total_mm": v}
                    for k, v in aggregated.items() if k[1] == "PRCP"
                ]
            if "heating_degree_days" in data_types:
                result["heating_degree_days"] = [
                    {"year": k[0], "value": v}
                    for k, v in aggregated.items() if k[1] == "HTDD"
                ]
            if "cooling_degree_days" in data_types:
                result["cooling_degree_days"] = [
                    {"year": k[0], "value": v}
                    for k, v in aggregated.items() if k[1] == "CLDD"
                ]
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch NOAA yearly data for {entity}: {e}")

        return result

    def _fetch_monthly(
        self, entity: str, location_id: str, start_year: str, data_types: list[str],
    ) -> dict[str, Any]:
        """Fetch monthly summaries from GSOM dataset."""
        end_date = f"{datetime.now().year}-01-01"
        start_date = f"{start_year}-01-01"

        noaa_types = []
        if "monthly_temperature" in data_types:
            noaa_types.extend(["TAVG", "TMAX", "TMIN"])
        if "monthly_precipitation" in data_types:
            noaa_types.append("PRCP")

        if not noaa_types:
            return {}

        result = {}
        try:
            raw = self.fetch(
                "data",
                datasetid="GSOM",
                locationid=location_id,
                datatypeid=",".join(noaa_types),
                startdate=start_date,
                enddate=end_date,
                units="metric",
                limit=1000,
            )
            aggregated = self._aggregate_stations(raw.get("results", []), yearly=False)

            if "monthly_temperature" in data_types:
                result["temperature"] = [
                    {"date": k[0], "type": k[1], "value_celsius": v}
                    for k, v in aggregated.items() if k[1] in ("TAVG", "TMAX", "TMIN")
                ]
            if "monthly_precipitation" in data_types:
                result["precipitation"] = [
                    {"date": k[0], "value_mm": v}
                    for k, v in aggregated.items() if k[1] == "PRCP"
                ]
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch NOAA monthly data for {entity}: {e}")

        return result

    @staticmethod
    def _aggregate_stations(results: list[dict], yearly: bool = False) -> dict:
        """Average per-station readings into one value per time period + datatype.

        Args:
            results: Raw NOAA API results (per-station records).
            yearly: If True, truncate date to year; otherwise to YYYY-MM.

        Returns:
            Dict of (date, datatype) → rounded average value.
        """
        from collections import defaultdict
        buckets = defaultdict(list)
        for r in results:
            datatype = r.get("datatype", "")
            raw_date = r.get("date", "")
            date = raw_date[:4] if yearly else raw_date[:7]
            value = r.get("value")
            if value is not None:
                buckets[(date, datatype)].append(value)

        return {
            k: round(sum(v) / len(v), 1)
            for k, v in sorted(buckets.items())
        }
