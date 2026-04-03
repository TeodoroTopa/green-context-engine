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


def build_draft_prompt(enriched) -> str:
    """Build the user message for draft generation.

    Args:
        enriched: An EnrichedStory instance.
    """
    angles_text = "\n".join(f"- {a}" for a in enriched.suggested_angles)

    return f"""\
Write an energy intelligence brief using ONLY the story and data below.
You must not introduce any numbers or statistics beyond what appears in these sections.

## Story
Title: {enriched.story.title}
Source: {enriched.story.source} ({enriched.story.url})
Summary: {enriched.story.summary}

## Data Summary (from Ember API)
{enriched.data_summary}

REMINDER: Use only the numbers above. If data is limited, write a shorter brief and note the gaps.

## Suggested Angles
{angles_text}

## Output Format
Write in markdown. Use this structure (skip sections that don't apply):
1. **The Hook** — the specific event or data point (REQUIRED)
2. **The Data Context** — relevant numbers from sources (REQUIRED — only from data above)
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
