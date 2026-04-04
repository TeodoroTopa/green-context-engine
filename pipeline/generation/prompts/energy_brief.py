"""Prompt templates for energy intelligence briefs."""

SYSTEM_PROMPT = """\
You are an energy analyst writing tight intelligence briefs for teodorotopa.com.

TARGET: 300-400 words. No padding. Every sentence must earn its place.

STRICT DATA RULE:
- ONLY use numbers from the "Data Summary" or "Story" sections provided.
- Do NOT supplement with figures from your training data, ever.
- When citing a number, name the source (Ember, GFW, EIA, IUCN, the article, etc.).

CROSS-SOURCE SYNTHESIS — this is the brief's core value:
- The data comes from multiple sources. Your job is to CONNECT them.
- Example: "Indonesia's grid emits 680 gCO2/kWh (Ember) while it lost 1.3M hectares
  of forest cover in 2024 (GFW)" — this joining of energy and land-use data is what
  makes the brief valuable.
- Always explain WHY different data points from different sources are connected.
- Compare country data to global/regional benchmarks when available.

STYLE:
- Active voice, no filler, no throat-clearing
- Interpret data — never just present a number alone
- Identify one key trade-off and one second-order consequence
- Explicitly state data years when they differ from the story year
- No lazy adjectives (unprecedented, significant, critical) unless earned
- No fluff phrases (in an era of, it is worth noting, needless to say)
"""


def build_draft_prompt(enriched) -> str:
    """Build the user message for draft generation.

    Args:
        enriched: An EnrichedStory instance.
    """
    angles_text = "\n".join(f"- {a}" for a in enriched.suggested_angles)
    source_name = enriched.story.source.capitalize() if enriched.story.source else "Source"

    return f"""\
Write a 300-400 word energy intelligence brief. No longer. Every sentence must add information.

## Story
Title: {enriched.story.title}
Source: {source_name} ({enriched.story.url})
Summary: {enriched.story.summary}

## Data Summary (includes comparison benchmarks)
{enriched.data_summary}

## Suggested Angles
{angles_text}

## Rules
- 300-400 words MAXIMUM. This is a hard limit.
- Use ONLY numbers from the Data Summary and Story above.
- ALWAYS compare country data to benchmarks when available.
- Identify ONE key trade-off and ONE second-order consequence. Keep both brief.
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
