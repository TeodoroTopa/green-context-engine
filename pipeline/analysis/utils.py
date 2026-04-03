"""Shared utilities for analysis modules."""

import re


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) that Claude sometimes wraps around JSON."""
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)
    return stripped.strip()
