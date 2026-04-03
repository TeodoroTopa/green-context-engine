"""Prompt templates for energy intelligence briefs."""

SYSTEM_PROMPT = """\
You are an energy analyst drafting an intelligence brief for teodorotopa.com.

Rules:
- Ground every claim in data from a named, verifiable source
- Interpret data — never just present a number alone
- Connect seemingly unrelated trends
- Present trade-offs: if something helps decarbonization but hurts habitat, say both
- Use active voice and clear structure
- NEVER use lazy adjectives ("unprecedented", "important", "critical") without earning them
- NEVER make sweeping generalizations or flowery empty declarations
- NEVER filter information toward a predetermined conclusion
"""


def build_draft_prompt(enriched) -> str:
    """Build the user message for draft generation.

    Args:
        enriched: An EnrichedStory instance.
    """
    angles_text = "\n".join(f"- {a}" for a in enriched.suggested_angles)

    return f"""\
Write an energy intelligence brief based on this story and data.

## Story
Title: {enriched.story.title}
Source: {enriched.story.source} ({enriched.story.url})
Summary: {enriched.story.summary}

## Data Summary
{enriched.data_summary}

## Suggested Angles
{angles_text}

## Output Format
Write in markdown. Use this structure (skip sections that don't apply):
1. **The Hook** — the specific event or data point (REQUIRED)
2. **The Data Context** — relevant numbers from sources (REQUIRED)
3. **The Ripple Effects** — second/third-order consequences
4. **The Trade-Offs** — what's gained and lost, with data on both sides
5. **The Take** — editorial perspective earned through the preceding evidence

Start with YAML frontmatter:
---
title: "..."
date: {enriched.story.published or "YYYY-MM-DD"}
sources:
  - name: Mongabay
    url: {enriched.story.url}
  - name: Ember
    url: https://ember-energy.org
status: draft
---
"""
