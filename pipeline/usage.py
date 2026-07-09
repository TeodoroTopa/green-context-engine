"""Token usage tracking and cost estimation for Claude API calls.

Prices are per-model (per 1M tokens). Batch API requests are billed at 50%, so
pass ``batch=True`` when the call went through the Message Batches API.

In local CLI-proxy mode calls are billed against the subscription, not per
token, so cost figures there are informational only.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Per-model pricing, USD per 1M tokens: (input, output).
# Standard (non-intro) rates — conservative for budgeting.
_PRICES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
}
# Used when a model is unknown/None — Sonnet rate is a safe over-estimate for
# the cheap stages and correct for the Sonnet stages.
_DEFAULT_PRICE = (3.0, 15.0)

BATCH_MULTIPLIER = 0.5


def price_for(model: str | None) -> tuple[float, float]:
    """Return (input_price, output_price) per 1M tokens for a model id.

    Matches by longest known prefix so dated/suffixed variants still resolve.
    """
    if model:
        if model in _PRICES:
            return _PRICES[model]
        for key, price in _PRICES.items():
            if model.startswith(key):
                return price
    return _DEFAULT_PRICE


def estimate_cost(
    model: str | None, input_tokens: int, output_tokens: int, batch: bool = False
) -> float:
    """USD cost for a single call given token counts."""
    in_price, out_price = price_for(model)
    cost = (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return cost * BATCH_MULTIPLIER if batch else cost


class UsageTracker:
    """Accumulates token usage across multiple API calls for a single draft."""

    def __init__(self):
        self.calls: list[dict] = []

    def track(
        self, response, label: str, model: str | None = None, batch: bool = False
    ) -> None:
        """Record usage from an Anthropic API response.

        Args:
            response: The response object from client.messages.create().
            label: Human-readable name for the call (e.g. "draft_generation").
            model: The model id used (for accurate per-model pricing). Falls
                back to response.model, then to the default price.
            batch: True if the call was billed via the Batch API (50%).
        """
        usage = response.usage
        resolved_model = model or getattr(response, "model", None)
        entry = {
            "label": label,
            "model": resolved_model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "batch": batch,
        }
        self.calls.append(entry)
        logger.debug(
            "API [%s] %s: %d in + %d out%s",
            label, resolved_model, usage.input_tokens, usage.output_tokens,
            " (batch)" if batch else "",
        )

    def total_tokens(self) -> tuple[int, int]:
        """Return (total_input_tokens, total_output_tokens)."""
        total_in = sum(c["input_tokens"] for c in self.calls)
        total_out = sum(c["output_tokens"] for c in self.calls)
        return total_in, total_out

    def estimated_cost_usd(self) -> float:
        """Cost estimate summed per-call using each call's model and batch flag."""
        return sum(
            estimate_cost(
                c.get("model"), c["input_tokens"], c["output_tokens"], c.get("batch", False)
            )
            for c in self.calls
        )

    def summary(self) -> str:
        """Human-readable summary of usage for this draft."""
        total_in, total_out = self.total_tokens()
        cost = self.estimated_cost_usd()
        lines = [f"Token usage: {total_in:,} in + {total_out:,} out = ${cost:.4f}"]
        for c in self.calls:
            flag = " (batch)" if c.get("batch") else ""
            lines.append(
                f"  {c['label']} [{c.get('model')}]{flag}: "
                f"{c['input_tokens']:,} in + {c['output_tokens']:,} out"
            )
        return "\n".join(lines)


class BudgetExceeded(RuntimeError):
    """Raised/handled when a run would exceed the daily spend cap."""


class BudgetGuard:
    """Tracks cumulative estimated spend for a run against a daily cap.

    The cap defaults to $0.50 and is overridable via PIPELINE_DAILY_BUDGET_USD.
    Call ``check(est)`` before a (batch) submit; it raises BudgetExceeded if the
    projected total would cross the cap. Call ``record(actual)`` after retrieval
    to keep the running total accurate.
    """

    DEFAULT_CAP = 0.50

    def __init__(self, cap_usd: float | None = None, tracker: "UsageTracker | None" = None):
        if cap_usd is None:
            raw = os.getenv("PIPELINE_DAILY_BUDGET_USD")
            cap_usd = float(raw) if raw else self.DEFAULT_CAP
        self.cap = cap_usd
        self._tracker = tracker  # when set, spend is derived from all tracked calls
        self.spent = 0.0         # manual accumulator (used when no tracker)

    def spent_so_far(self) -> float:
        """Total spend so far — from the tracker if bound, else the accumulator.

        A bound tracker accounts for *every* call (sync Haiku stages and batched
        Sonnet stages alike), so the cap is honored precisely.
        """
        if self._tracker is not None:
            return self._tracker.estimated_cost_usd()
        return self.spent

    def remaining(self) -> float:
        return max(0.0, self.cap - self.spent_so_far())

    def check(self, est_cost: float) -> None:
        """Raise BudgetExceeded if adding est_cost would cross the cap."""
        spent = self.spent_so_far()
        if spent + est_cost > self.cap:
            raise BudgetExceeded(
                f"Projected spend ${spent + est_cost:.4f} exceeds daily cap "
                f"${self.cap:.2f} (already spent ${spent:.4f}, "
                f"this step ~${est_cost:.4f})."
            )

    def record(self, actual_cost: float) -> None:
        """Manually add spend (no-op semantics when a tracker is bound)."""
        self.spent += actual_cost
