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

    def get_generation_context(self, entity: str, **kwargs: Any) -> dict[str, Any]:
        """Get climate data for a country or US state.

        Despite the name (inherited from BaseSource), this returns climate
        data (temperature, precipitation), not electricity generation.

        Args:
            entity: Country name or US state name
            **kwargs: Optional 'start_date' (YYYY, default: 1 year ago)

        Returns:
            Dict with keys: entity, temperature (list), precipitation (list),
            source ("noaa")
        """
        # Determine location ID
        location_id = US_STATE_FIPS.get(entity) or COUNTRY_FIPS.get(entity)
        if not location_id:
            logger.debug(f"NOAA: no FIPS code for '{entity}', skipping")
            return {"entity": entity, "temperature": [], "precipitation": [], "source": "noaa"}

        start_date = kwargs.get("start_date", "")
        if not start_date:
            # Default: last full year
            last_year = datetime.now().year - 1
            start_date = str(last_year)

        return self._fetch_climate_summary(entity, location_id, start_date)

    def _fetch_climate_summary(
        self, entity: str, location_id: str, start_year: str,
    ) -> dict[str, Any]:
        """Fetch monthly temperature and precipitation summaries."""
        # NOAA monthly data: up to 10-year range
        end_date = f"{datetime.now().year}-01-01"
        start_date = f"{start_year}-01-01"

        temperature = []
        precipitation = []

        try:
            # Fetch monthly climate summaries (GSOM dataset)
            raw = self.fetch(
                "data",
                datasetid="GSOM",
                locationid=location_id,
                datatypeid="TAVG,TMAX,TMIN,PRCP",
                startdate=start_date,
                enddate=end_date,
                units="metric",
                limit=1000,
            )
            results = raw.get("results", [])

            # GSOM returns per-station readings. Aggregate by month+datatype.
            from collections import defaultdict
            buckets = defaultdict(list)  # key: (date, datatype) → [values]
            for r in results:
                datatype = r.get("datatype", "")
                date = r.get("date", "")[:7]  # YYYY-MM
                value = r.get("value")
                if value is not None:
                    # GSOM returns values already in °C (temp) and mm (precip)
                    # — no /10 conversion needed (unlike GHCND daily data)
                    buckets[(date, datatype)].append(value)

            for (date, datatype), values in sorted(buckets.items()):
                avg = sum(values) / len(values)
                if datatype in ("TAVG", "TMAX", "TMIN"):
                    temperature.append({
                        "date": date,
                        "type": datatype,
                        "value_celsius": round(avg, 1),
                    })
                elif datatype == "PRCP":
                    precipitation.append({
                        "date": date,
                        "value_mm": round(avg, 1),
                    })

        except requests.RequestException as e:
            logger.warning(f"Failed to fetch NOAA data for {entity}: {e}")

        return {
            "entity": entity,
            "temperature": temperature,
            "precipitation": precipitation,
            "source": "noaa",
        }
