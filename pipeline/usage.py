"""Token usage tracking for Claude API calls.

Tracks input/output tokens per API call and estimates cost.
Pricing based on Claude Sonnet (the model used for enrichment and drafting).
"""

import logging

logger = logging.getLogger(__name__)

# Sonnet 4 pricing (per token) — update if model changes
PRICE_PER_INPUT_TOKEN = 3.0 / 1_000_000   # $3 per 1M input tokens
PRICE_PER_OUTPUT_TOKEN = 15.0 / 1_000_000  # $15 per 1M output tokens


class UsageTracker:
    """Accumulates token usage across multiple API calls for a single draft."""

    def __init__(self):
        self.calls: list[dict] = []

    def track(self, response, label: str) -> None:
        """Record usage from an Anthropic API response.

        Args:
            response: The response object from client.messages.create()
            label: Human-readable name for the call (e.g. "entity_extraction")
        """
        usage = response.usage
        entry = {
            "label": label,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }
        self.calls.append(entry)
        logger.debug(
            f"API [{label}]: {usage.input_tokens} in + {usage.output_tokens} out"
        )

    def total_tokens(self) -> tuple[int, int]:
        """Return (total_input_tokens, total_output_tokens)."""
        total_in = sum(c["input_tokens"] for c in self.calls)
        total_out = sum(c["output_tokens"] for c in self.calls)
        return total_in, total_out

    def estimated_cost_usd(self) -> float:
        """Rough cost estimate based on Sonnet pricing."""
        total_in, total_out = self.total_tokens()
        return (total_in * PRICE_PER_INPUT_TOKEN) + (total_out * PRICE_PER_OUTPUT_TOKEN)

    def summary(self) -> str:
        """Human-readable summary of usage for this draft."""
        total_in, total_out = self.total_tokens()
        cost = self.estimated_cost_usd()
        lines = [f"Token usage: {total_in:,} in + {total_out:,} out = ${cost:.4f}"]
        for c in self.calls:
            lines.append(f"  {c['label']}: {c['input_tokens']:,} in + {c['output_tokens']:,} out")
        return "\n".join(lines)
