"""Scheduled morning entry point — batched, budget-guarded pipeline.

Runs the discover → enrich → draft → edit flow with the two Sonnet stages
(drafter, editor) submitted through the Message Batches API (50% off) and the
cheap Haiku stages synchronous. Requires the real Anthropic API, so it forces
PIPELINE_MODE=prod (Batch is unavailable via the CLI proxy).

Usage:
    python scripts/run_pipeline_batched.py
    python scripts/run_pipeline_batched.py --source mongabay --max-stories 1
"""

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Batch needs the API client — never the CLI proxy.
os.environ["PIPELINE_MODE"] = "prod"

from pipeline.orchestrator import Pipeline  # noqa: E402
from pipeline.usage import BudgetGuard  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Run the batched morning pipeline")
    parser.add_argument("--source", help="Filter to a specific source (e.g. mongabay)")
    parser.add_argument("--max-stories", type=int, default=5, help="Max stories (default: 5)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    logging.getLogger(__name__).info(
        "Daily budget cap: $%.2f", BudgetGuard().cap
    )

    pipeline = Pipeline()
    drafts = pipeline.run_batched(source=args.source, max_stories=args.max_stories)

    print(f"\nGenerated {len(drafts)} draft(s):")
    for d in drafts:
        print(f"  {d}")


if __name__ == "__main__":
    main()
