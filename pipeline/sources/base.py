from abc import ABC, abstractmethod
from typing import Any


class BaseSource(ABC):
    """Base class for all data source connectors.

    Every source (Ember, EIA, GFW, etc.) implements this interface
    so the rest of the pipeline can work with any source uniformly.
    """

    @abstractmethod
    def fetch(self, endpoint: str, **params: Any) -> dict[str, Any]:
        """Fetch raw data from an API endpoint. Returns parsed JSON."""
        ...

    @abstractmethod
    def get_generation_context(self, entity: str, **kwargs: Any) -> dict[str, Any]:
        """Get energy generation data relevant to a story about this entity (country/region)."""
        ...
