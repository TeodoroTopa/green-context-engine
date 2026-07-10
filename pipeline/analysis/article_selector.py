"""Article selector — AI agent that picks stories best served by available data.

Given a batch of candidate article titles and the data catalog, ranks stories
by how well the available data sources can add meaningful context. One Claude
call for the whole batch, using only titles to keep the prompt small.
"""

import json
import logging

from pipeline.analysis.utils import strip_code_fences
from pipeline.monitors.rss_monitor import Story
from pipeline.usage import UsageTracker

logger = logging.getLogger(__name__)

SELECTOR_PROMPT = """\
Pick the {max_stories} articles that would benefit most from the data sources below.
Rank by how well the available data can add context the reader wouldn't get from
the headline alone.

<examples>
GOOD FIT: "Rooftop solar reaches 20% of Puerto Rico's generation" — EIA has
state/territory generation mix, Ember has global benchmarks. Data directly
contextualizes the headline number.

GOOD FIT: "Indonesia's deforestation surges 66% in 2025" — GFW has tree cover
loss + drivers for Indonesia, Ember has grid carbon intensity. Two sources,
clear geographic entity, cross-domain synthesis possible. (One of many good
shapes — not the template. A market/industry story can fit just as well.)

GOOD FIT: "US utility-scale battery storage capacity nearly doubles in 2025"
— EIA has state-level storage capacity figures, Ember has global storage
benchmarks. A market/industry headline grounded in the same kind of
cross-source data as the examples above.

POOR FIT: "TCL Zhonghuan acquires DAS Solar" — corporate M&A with no clear
country-level energy or environmental angle the data can illuminate.

POOR FIT: "Opinion: why forest protection needs a new global treaty" —
commentary with no specific geographic entity or dataset to ground it;
could run on any outlet and is still a poor fit regardless.
</examples>

<rules>
- Judge by title only. Don't infer article content beyond what the title says.
- This batch includes stories from multiple news sources — judge each purely
  on data fit; a source's typical beat is not a signal of quality.
- Prefer stories where 2+ data sources are relevant (cross-source synthesis).
- Prefer clear geographic entities that exist in the catalog.
- Do not select more than {max_per_source} stories from the same source;
  prefer diversity across sources at equal data-fit quality.
- Return JSON: {{"selected": [0, 3, 7], "reasoning": "..."}}
  (indices into the titles list, best first)
- Keep your reasoning under 250 words.
</rules>

<titles>
{titles}
</titles>

<catalog>
{catalog}
</catalog>
"""


def cap_by_source(
    ordered_stories: list[Story],
    max_stories: int,
    max_per_source: int | None,
) -> list[Story]:
    """Take up to max_stories from ordered_stories (best-first) without
    exceeding max_per_source picks from any one story.source.

    Returns fewer than max_stories if diversity can't be satisfied — does
    NOT backfill from a source that's already hit its cap.
    """
    if not max_per_source:
        return ordered_stories[:max_stories]

    selected = []
    counts: dict[str, int] = {}
    for story in ordered_stories:
        if len(selected) >= max_stories:
            break
        if counts.get(story.source, 0) >= max_per_source:
            continue
        selected.append(story)
        counts[story.source] = counts.get(story.source, 0) + 1
    return selected


def select_best_stories(
    client,
    model: str,
    stories: list[Story],
    catalog_text: str,
    max_stories: int,
    tracker: UsageTracker | None = None,
    max_per_source: int | None = None,
) -> list[Story]:
    """Pick the stories best served by available data sources.

    Args:
        client: Anthropic API client (or ClaudeCodeClient).
        model: Model ID to use.
        stories: Candidate stories (post-dedup). Caller should shuffle these
            before passing in, so fallback paths aren't feed-config-ordered.
        catalog_text: Formatted catalog from catalog.load_catalog().
        max_stories: How many to select.
        tracker: Optional usage tracker.
        max_per_source: Cap on picks from any one story.source. None disables
            the cap.

    Returns:
        Ordered list of selected Story objects (best fit first). May be
        shorter than max_stories if the source cap can't be fully satisfied.
        Falls back to the first N (source-capped) stories on failure.
    """
    titles = "\n".join(f"{i}: {s.title}" for i, s in enumerate(stories))

    prompt = SELECTOR_PROMPT.format(
        max_stories=max_stories,
        max_per_source=max_per_source or "N",
        titles=titles,
        catalog=catalog_text,
    )

    response = client.messages.create(
        model=model,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.track(response, "article_selector", model=model)

    text = strip_code_fences(response.content[0].text)
    try:
        result = json.loads(text)
        indices = result.get("selected", [])
        reasoning = result.get("reasoning", "")

        # Validate indices
        valid = [i for i in indices if isinstance(i, int) and 0 <= i < len(stories)]
        if not valid:
            logger.warning("Selector returned no valid indices, using first N")
            return cap_by_source(stories, max_stories, max_per_source)

        ranked = [stories[i] for i in valid]
        selected = cap_by_source(ranked, max_stories, max_per_source)
        logger.info(
            f"Selector picked {len(selected)} from {len(stories)} candidates — {reasoning[:100]}"
        )
        return selected

    except json.JSONDecodeError:
        logger.warning(f"Could not parse selector response: {text[:200]}")
        return cap_by_source(stories, max_stories, max_per_source)
