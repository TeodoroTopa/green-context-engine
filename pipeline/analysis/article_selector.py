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
GOOD FIT: "Indonesia's deforestation surges 66% in 2025" — GFW has tree cover
loss + drivers for Indonesia, Ember has grid carbon intensity. Two sources,
clear geographic entity, cross-domain synthesis possible.

GOOD FIT: "Rooftop solar reaches 20% of Puerto Rico's generation" — EIA has
state/territory generation mix, Ember has global benchmarks. Data directly
contextualizes the headline number.

POOR FIT: "TCL Zhonghuan acquires DAS Solar" — corporate M&A with no clear
country-level energy or environmental angle the data can illuminate.

POOR FIT: "Podcast: EV deliveries from Tesla, Rivian" — product news roundup,
no single geographic or policy story the data can ground.
</examples>

<rules>
- Judge by title only. Don't infer article content beyond what the title says.
- Prefer stories where 2+ data sources are relevant (cross-source synthesis).
- Prefer clear geographic entities that exist in the catalog.
- Return JSON: {{"selected": [0, 3, 7], "reasoning": "..."}}
  (indices into the titles list, best first)
- Keep your reasoning brief — 1-2 sentences max.
</rules>

<titles>
{titles}
</titles>

<catalog>
{catalog}
</catalog>
"""


def select_best_stories(
    client,
    model: str,
    stories: list[Story],
    catalog_text: str,
    max_stories: int,
    tracker: UsageTracker | None = None,
) -> list[Story]:
    """Pick the stories best served by available data sources.

    Args:
        client: Anthropic API client (or ClaudeCodeClient).
        model: Model ID to use.
        stories: Candidate stories (post-dedup).
        catalog_text: Formatted catalog from catalog.load_catalog().
        max_stories: How many to select.
        tracker: Optional usage tracker.

    Returns:
        Ordered list of selected Story objects (best fit first).
        Falls back to first N stories on failure.
    """
    titles = "\n".join(f"{i}: {s.title}" for i, s in enumerate(stories))

    prompt = SELECTOR_PROMPT.format(
        max_stories=max_stories,
        titles=titles,
        catalog=catalog_text,
    )

    response = client.messages.create(
        model=model,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    if tracker:
        tracker.track(response, "article_selector")

    text = strip_code_fences(response.content[0].text)
    try:
        result = json.loads(text)
        indices = result.get("selected", [])
        reasoning = result.get("reasoning", "")

        # Validate indices
        valid = [i for i in indices if isinstance(i, int) and 0 <= i < len(stories)]
        if not valid:
            logger.warning("Selector returned no valid indices, using first N")
            return stories[:max_stories]

        selected = [stories[i] for i in valid[:max_stories]]
        logger.info(
            f"Selector picked {len(selected)} from {len(stories)} candidates — {reasoning[:100]}"
        )
        return selected

    except json.JSONDecodeError:
        logger.warning(f"Could not parse selector response: {text[:200]}")
        return stories[:max_stories]
