"""Prompt templates for energy intelligence briefs."""

SYSTEM_PROMPT = """\
You are an energy analyst drafting an intelligence brief for teodorotopa.com.

STRICT DATA RULE — this is the most important rule:
- The ONLY numbers, statistics, and data points you may use are those that appear in the
  "Data Summary" or "Story" sections provided to you. No exceptions.
- Do NOT supplement with figures from your training data, even if you are confident they are correct.
- If the provided data is thin, write a shorter brief that honestly states what data is available
  and what is missing. A brief that says "data is limited" is better than one with made-up numbers.
- When citing a number, name the source it came from (Ember, the article, etc.).

Other rules:
- Interpret data — never just present a number alone
- Connect seemingly unrelated trends
- Present trade-offs: if something helps decarbonization but hurts habitat, say both
- Use active voice and clear structure
- NEVER use lazy adjectives ("unprecedented", "important", "critical") without earning them
- NEVER make sweeping generalizations or flowery empty declarations
- NEVER filter information toward a predetermined conclusion
"""


def _format_ripple_effects(effects: list[str]) -> str:
    """Format ripple effects for the prompt."""
    if not effects:
        return "No pre-analyzed ripple effects available."
    return "\n".join(f"- {e}" for e in effects)


def _format_tradeoffs(tradeoffs: list[dict]) -> str:
    """Format trade-offs for the prompt."""
    if not tradeoffs:
        return "No pre-analyzed trade-offs available."
    parts = []
    for t in tradeoffs:
        parts.append(
            f"**{t.get('tension', 'Trade-off')}**\n"
            f"  Gained: {t.get('gained', '?')}\n"
            f"  Lost: {t.get('lost', '?')}"
        )
    return "\n\n".join(parts)


def _format_landscape(landscape: dict) -> str:
    """Format landscape analysis for the prompt."""
    if not landscape:
        return "No pre-analyzed landscape data available."
    parts = []
    if landscape.get("key_players"):
        parts.append("Key players:\n" + "\n".join(f"- {p}" for p in landscape["key_players"]))
    if landscape.get("implementation_state"):
        parts.append(f"Implementation state: {landscape['implementation_state']}")
    if landscape.get("recent_developments"):
        parts.append("Recent developments:\n" + "\n".join(f"- {d}" for d in landscape["recent_developments"]))
    if landscape.get("policy_context"):
        parts.append(f"Policy context: {landscape['policy_context']}")
    return "\n\n".join(parts) if parts else "No pre-analyzed landscape data available."


def build_draft_prompt(enriched) -> str:
    """Build the user message for draft generation.

    Args:
        enriched: An EnrichedStory instance.
    """
    angles_text = "\n".join(f"- {a}" for a in enriched.suggested_angles)
    ripple_text = _format_ripple_effects(enriched.ripple_effects)
    tradeoffs_text = _format_tradeoffs(enriched.tradeoffs)
    landscape_text = _format_landscape(enriched.landscape)

    # Use actual source name, not hardcoded Mongabay
    source_name = enriched.story.source.capitalize() if enriched.story.source else "Source"

    return f"""\
Write an energy intelligence brief using ONLY the story and data below.
You must not introduce any numbers or statistics beyond what appears in these sections.

## Story
Title: {enriched.story.title}
Source: {source_name} ({enriched.story.url})
Summary: {enriched.story.summary}

## Data Summary (from Ember API)
{enriched.data_summary}

## Pre-Analyzed Ripple Effects
{ripple_text}

## Pre-Analyzed Trade-Offs
{tradeoffs_text}

## Pre-Analyzed Landscape
{landscape_text}

REMINDER: Use only the numbers from the Data Summary and Story above. If data is limited,
write a shorter brief and note the gaps. The ripple effects and trade-offs above are
pre-analyzed — incorporate them into the relevant sections, but verify any numbers
against the Data Summary before using them.

## Suggested Angles
{angles_text}

## Output Format
Write in markdown. Use this structure (skip sections that don't apply):
1. **The Hook** — the specific event or data point (REQUIRED)
2. **The Data Context** — relevant numbers from sources (REQUIRED — only from data above)
3. **The Landscape** — who's working on this, what stage (use pre-analyzed landscape above)
4. **The Ripple Effects** — second/third-order consequences (use pre-analyzed effects above)
5. **The Trade-Offs** — what's gained and lost (use pre-analyzed trade-offs above)
6. **The Take** — editorial perspective earned through the preceding evidence

Start with YAML frontmatter:
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
"""
