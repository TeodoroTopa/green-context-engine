"""Data catalog loader — reads source catalogs for the data strategist.

Each YAML file in config/data_catalog/ describes a data source: what data
it provides, what entities are available, and how to connect to it.
The strategist uses this to decide what to fetch for each article.
"""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CATALOG_DIR = Path("config/data_catalog")


def load_catalog() -> str:
    """Read all data catalog YAMLs and return a formatted description.

    This is what gets injected into the strategist prompt so it knows
    what data sources and entities are available.
    """
    catalogs = get_available_sources()
    if not catalogs:
        return "No data sources configured."

    parts = []
    for name, config in catalogs.items():
        lines = [f"## {name.upper()}: {config.get('description', '')}"]
        lines.append(f"Data types: {', '.join(config.get('data_types', []))}")

        if config.get("coverage"):
            lines.append(f"Coverage: {config['coverage']}")

        entities = config.get("entities", {})
        for group_name, group_entities in entities.items():
            if isinstance(group_entities, list):
                lines.append(f"{group_name}: {', '.join(group_entities)}")
            elif isinstance(group_entities, dict):
                # Nested (regions → countries)
                for region, countries in group_entities.items():
                    lines.append(f"{region}: {', '.join(countries[:10])}")
                    if len(countries) > 10:
                        lines.append(f"  ... and {len(countries) - 10} more")

        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def get_available_sources() -> dict[str, dict]:
    """Return source configs keyed by source name.

    Each config includes: description, connector, env_key, data_types,
    entities, and optionally coverage.
    """
    if not CATALOG_DIR.exists():
        logger.warning(f"Catalog directory not found: {CATALOG_DIR}")
        return {}

    sources = {}
    for path in sorted(CATALOG_DIR.glob("*.yaml")):
        try:
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            name = config.get("source", path.stem)
            sources[name] = config
        except (yaml.YAMLError, OSError) as e:
            logger.warning(f"Failed to load catalog {path.name}: {e}")

    return sources
