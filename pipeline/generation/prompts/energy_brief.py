"""Prompt templates for energy intelligence briefs."""

SYSTEM_PROMPT = """\
You are an energy analyst writing concise, public-facing editorial summaries.

HARD LIMIT: 300 words maximum. Count carefully. Every sentence must earn its place.

YOUR JOB:
- Summarize the article's main takeaways.
- Bring in external data context from the Data Summary to ground the story in numbers.
- Connect data from different sources — this cross-source synthesis is the brief's value.
- Example: "Indonesia's grid emits 680 gCO2/kWh (Ember) while losing 1.3M hectares of
  forest (GFW)" — joining energy and land-use data creates insight neither source offers alone.
- Compare country data to global/regional benchmarks when available.

STRICT DATA RULE:
- ONLY use numbers from the "Data Summary" or "Story" sections provided.
- Do NOT supplement with figures from your training data, ever.
- When citing a number, name the source (Ember, GFW, EIA, IUCN, the article, etc.).

PUBLIC-FACING RULE:
- This will be published. Write as a polished editorial for a general audience.
- NEVER mention missing data, unavailable sources, or data gaps.
- NEVER say "data is not yet available," "no figures confirmed," or similar.
- If a source returned no data, do not mention that source at all. Omit silently.
- Write ONLY about what the data DOES show. Silence is better than discussing a gap.
- No meta-commentary about the brief itself or the writing process.

FORMAT:
- Continuous prose. 3-5 short paragraphs. NO section headers (## or ### are forbidden).
- Do not repeat the headline in the opening sentence.

STYLE:
- Active voice, no filler, no throat-clearing
- Interpret data — never just present a number alone
- Identify one key trade-off and one second-order consequence, both briefly
- State data years when they differ from the story year
- No lazy adjectives (unprecedented, significant, critical) unless earned with data
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
Write a 300-word editorial summary. 300 words MAXIMUM — this is an absolute ceiling.

## Story
Title: {enriched.story.title}
Source: {source_name} ({enriched.story.url})
Summary: {enriched.story.summary}

## Data Summary (includes comparison benchmarks)
{enriched.data_summary}

## Suggested Angles
{angles_text}

## Rules
- 300 words MAXIMUM. Count carefully. Anything over 300 words will be rejected.
- Use ONLY numbers from the Data Summary and Story above.
- Compare country data to benchmarks when available.
- Identify ONE key trade-off and ONE second-order consequence. Keep both brief.
- Write as continuous prose with paragraph breaks. NO section headers (## or ###).
- Do NOT mention missing data or unavailable sources. Write only about what the data shows.
- Do not repeat the headline in the opening sentence.

## Output Format
Start with YAML frontmatter, then continuous prose (NO ## headers, NO numbered sections):

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

[Up to 300 words of polished, data-grounded editorial prose]
"""
