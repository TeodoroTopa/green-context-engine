"""Tests for usage tracking, per-model pricing, and the budget guard."""

from types import SimpleNamespace

import pytest

from pipeline.usage import (
    BudgetExceeded,
    BudgetGuard,
    UsageTracker,
    estimate_cost,
    price_for,
)


def _resp(input_tokens, output_tokens, model="claude-sonnet-5"):
    return SimpleNamespace(
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        model=model,
    )


def test_price_for_known_and_prefix_match():
    assert price_for("claude-haiku-4-5") == (1.0, 5.0)
    assert price_for("claude-sonnet-5") == (3.0, 15.0)
    # dated/suffixed variants resolve by prefix
    assert price_for("claude-haiku-4-5-20251001") == (1.0, 5.0)
    # unknown -> default (sonnet) pricing
    assert price_for("mystery-model") == (3.0, 15.0)
    assert price_for(None) == (3.0, 15.0)


def test_estimate_cost_and_batch_discount():
    full = estimate_cost("claude-sonnet-5", 1_000_000, 1_000_000, batch=False)
    assert full == pytest.approx(3.0 + 15.0)
    half = estimate_cost("claude-sonnet-5", 1_000_000, 1_000_000, batch=True)
    assert half == pytest.approx((3.0 + 15.0) * 0.5)


def test_tracker_sums_per_model():
    t = UsageTracker()
    t.track(_resp(1_000_000, 0, "claude-haiku-4-5"), "selector", model="claude-haiku-4-5")
    t.track(_resp(0, 1_000_000, "claude-sonnet-5"), "drafter", model="claude-sonnet-5")
    # 1M haiku input ($1) + 1M sonnet output ($15)
    assert t.estimated_cost_usd() == pytest.approx(1.0 + 15.0)
    assert t.total_tokens() == (1_000_000, 1_000_000)


def test_tracker_batch_flag_halves_cost():
    t = UsageTracker()
    t.track(_resp(1_000_000, 0, "claude-sonnet-5"), "draft", model="claude-sonnet-5", batch=True)
    assert t.estimated_cost_usd() == pytest.approx(3.0 * 0.5)


def test_budget_guard_default_cap(monkeypatch):
    monkeypatch.delenv("PIPELINE_DAILY_BUDGET_USD", raising=False)
    g = BudgetGuard()
    assert g.cap == pytest.approx(0.50)


def test_budget_guard_env_override(monkeypatch):
    monkeypatch.setenv("PIPELINE_DAILY_BUDGET_USD", "0.10")
    g = BudgetGuard()
    assert g.cap == pytest.approx(0.10)


def test_budget_guard_tracker_bound_accounts_for_all_spend():
    """A tracker-bound guard counts sync + batch calls, not just recorded ones."""
    t = UsageTracker()
    g = BudgetGuard(cap_usd=0.10, tracker=t)
    assert g.spent_so_far() == pytest.approx(0.0)
    # 1M haiku input = $1.00 tracked -> over a $0.10 cap already
    t.track(_resp(1_000_000, 0, "claude-haiku-4-5"), "selector", model="claude-haiku-4-5")
    assert g.spent_so_far() == pytest.approx(1.0)
    with pytest.raises(BudgetExceeded):
        g.check(0.0)


def test_budget_guard_check_raises_over_cap():
    g = BudgetGuard(cap_usd=0.10)
    g.check(0.05)  # under cap, ok
    g.record(0.05)
    g.check(0.04)  # 0.09 total, ok
    g.record(0.04)
    with pytest.raises(BudgetExceeded):
        g.check(0.05)  # 0.14 > 0.10
    assert g.remaining() == pytest.approx(0.01)
