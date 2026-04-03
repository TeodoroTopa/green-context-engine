"""Prompt templates for energy intelligence briefs."""

SYSTEM_PROMPT = """\
You are an energy analyst writing tight intelligence briefs for teodorotopa.com.

TARGET: 300-400 words. No padding. Every sentence must earn its place.

STRICT DATA RULE:
- ONLY use numbers from the "Data Summary" or "Story" sections provided.
- Do NOT supplement with figures from your training data, ever.
- When citing a number, name the source (Ember, the article, etc.).

COMPARISON RULE:
- When presenting a country's carbon intensity or generation mix, ALWAYS compare
  to the global benchmarks provided. "680 gCO2/kWh" means nothing alone —
  "680 gCO2/kWh, 44% above the global average of 471" tells a story.
- Use the benchmarks (World, OECD, regional) to situate the data.

STYLE:
- Active voice, no filler, no throat-clearing
- Interpret data — never just present a number alone
- One key trade-off per brief, stated plainly
- No lazy adjectives (unprecedented, significant, critical) unless earned
- No fluff phrases (in an era of, it is worth noting, needless to say)
"""


def _format_ripple_effects(effects: list[str]) -> str:
    """Format ripple effects for the prompt."""
    if not effects:
        return "None available."
    return "\n".join(f"- {e}" for e in effects)


def _format_tradeoffs(tradeoffs: list[dict]) -> str:
    """Format trade-offs for the prompt."""
    if not tradeoffs:
        return "None available."
    parts = []
    for t in tradeoffs:
        parts.append(
            f"**{t.get('tension', 'Trade-off')}**: "
            f"Gained: {t.get('gained', '?')} / Lost: {t.get('lost', '?')}"
        )
    return "\n".join(parts)


def _format_landscape(landscape: dict) -> str:
    """Format landscape analysis for the prompt."""
    if not landscape:
        return "None available."
    parts = []
    if landscape.get("key_players"):
        parts.append("Players: " + ", ".join(landscape["key_players"]))
    if landscape.get("implementation_state"):
        parts.append(f"State: {landscape['implementation_state']}")
    if landscape.get("policy_context"):
        parts.append(f"Policy: {landscape['policy_context']}")
    return "\n".join(parts) if parts else "None available."


def build_draft_prompt(enriched) -> str:
    """Build the user message for draft generation.

    Args:
        enriched: An EnrichedStory instance.
    """
    angles_text = "\n".join(f"- {a}" for a in enriched.suggested_angles)
    ripple_text = _format_ripple_effects(enriched.ripple_effects)
    tradeoffs_text = _format_tradeoffs(enriched.tradeoffs)
    landscape_text = _format_landscape(enriched.landscape)

    source_name = enriched.story.source.capitalize() if enriched.story.source else "Source"

    return f"""\
Write a 300-400 word energy intelligence brief. No longer. Every sentence must add information.

## Story
Title: {enriched.story.title}
Source: {source_name} ({enriched.story.url})
Summary: {enriched.story.summary}

## Data Summary (from Ember API — includes global benchmarks for comparison)
{enriched.data_summary}

## Pre-Analyzed Context
Ripple effects: {ripple_text}
Trade-offs: {tradeoffs_text}
Landscape: {landscape_text}
Suggested angles: {angles_text}

## Rules
- 300-400 words MAXIMUM. This is a hard limit.
- Use ONLY numbers from the Data Summary and Story above.
- ALWAYS compare country data to global benchmarks when available.
- Pick ONE ripple effect and ONE trade-off — the most important ones. Skip the rest.
- No section headers. Write as continuous prose with paragraph breaks.
- Do not repeat the headline in the opening sentence.

## Output Format
Start with YAML frontmatter, then the brief as continuous prose (no ## headers):

---
title: "..."
date: {enriched.story.published or "YYYY-MM-DD"}
sources:
  - name: {source_name}
    url: {enriched.story.url}
  - name: Ember
    url: https://ember-energy.org
status: draft
---

[300-400 words of tight, data-grounded analysis with global comparisons]
"""
