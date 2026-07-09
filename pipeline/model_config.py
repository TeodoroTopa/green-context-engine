"""Per-stage model configuration loader.

Reads config/models.yaml and resolves a Claude model ID for a named pipeline
stage (selector, strategist, drafter, editor, verifier, feedback).

In local CLI-proxy mode the resolved ID is ignored by ClaudeCodeClient (the
CLI flag wins); in API/prod mode the Anthropic SDK honors it, giving us
per-stage cost tiering.
"""

import logging
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/models.yaml")

# Hard-coded safety net if the YAML is missing or a stage is absent both there
# and in its `default`. Kept in sync with config/models.yaml.
_BUILTIN_DEFAULTS = {
    "selector": "claude-haiku-4-5",
    "strategist": "claude-haiku-4-5",
    "drafter": "claude-sonnet-5",
    "editor": "claude-sonnet-5",
    "verifier": "claude-haiku-4-5",
    "feedback": "claude-sonnet-5",
}
_BUILTIN_FALLBACK = "claude-haiku-4-5"


@lru_cache(maxsize=1)
def _load(path: str = str(CONFIG_PATH)) -> dict:
    p = Path(path)
    if not p.exists():
        logger.warning("%s not found — using built-in model defaults", p)
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def model_for(stage: str) -> str:
    """Return the configured Claude model ID for a pipeline stage.

    Resolution order: config stages[stage] -> config default -> built-in
    per-stage default -> built-in fallback.
    """
    cfg = _load()
    stages = cfg.get("stages") or {}
    if stage in stages and stages[stage]:
        return stages[stage]
    if cfg.get("default"):
        return cfg["default"]
    return _BUILTIN_DEFAULTS.get(stage, _BUILTIN_FALLBACK)
