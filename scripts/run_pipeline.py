"""CLI entry point for the energy context engine pipeline.

Usage:
    python scripts/run_pipeline.py
    python scripts/run_pipeline.py --source mongabay
    python scripts/run_pipeline.py --max-stories 3
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path so imports work when running from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.orchestrator import Pipeline


def main():
    parser = argparse.ArgumentParser(description="Run the energy context engine pipeline")
    parser.add_argument("--source", help="Filter to a specific source (e.g. mongabay)")
    parser.add_argument("--max-stories", type=int, default=5, help="Max stories to process (default: 5)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    pipeline = Pipeline()
    drafts = pipeline.run(source=args.source, max_stories=args.max_stories)

    print(f"\nGenerated {len(drafts)} draft(s):")
    for d in drafts:
        print(f"  {d}")


if __name__ == "__main__":
    main()
