# Energy Context Engine

## What This Project Is

An automated AI pipeline that monitors renewable energy news and public data sources, enriches stories with data and analysis, and publishes "energy intelligence briefs" on teodorotopa.com. Runs daily, identifies noteworthy developments, gathers data context from APIs, traces ripple effects, and drafts posts for human review before publishing.

NOT a generic AI blog. Every post grounded in certified data, connecting trends, presenting trade-offs honestly. No fluff, no sweeping generalizations, no assertions without evidence.

## Architecture

`pipeline/sources/` → data connectors (one per source) | `pipeline/monitors/` → RSS + data monitoring | `pipeline/analysis/` → enrichment, ripple effects, trade-offs | `pipeline/generation/` → drafting + prompts + voice validation | `pipeline/orchestrator.py` → wires it all together | `content/{drafts,approved,published}/` → review queue | `data/{cache,reference}/` → cached API responses | `config/` → YAML configs | `tests/` + `scripts/`

Publishing: Option C (MVP) — pipeline outputs markdown, manually copy to website repo. Graduate to GitHub API push once stable.

## Tech Stack

Python 3.11+, Claude API (Anthropic SDK), requests, pandas, feedparser, pytest, pyyaml, python-dotenv

## Data Sources

**Phase 1 (MVP):** Ember API (electricity data, carbon intensity) + Mongabay RSS (environmental journalism)
**Phase 2:** EIA Open Data API + Carbon Brief RSS
**Phase 3:** Electricity Maps API + Global Forest Watch API
**Phase 4:** IUCN Red List + NOAA Climate Data

## Editorial Guidelines

### Always
- Ground every claim in data from a named, verifiable source
- Interpret data — never just present a number alone
- Connect seemingly unrelated trends (energy → land use → biodiversity → economics)
- Present trade-offs honestly; show WHY something matters
- Active voice, clear structure

### Never
- Lazy adjectives without earning them ("unprecedented," "important," "critical")
- Sweeping generalizations, single anecdotes as universal proof
- Flowery empty declarations, jargon without context
- Filtering information toward a predetermined conclusion

### Post Structure
1. **The Hook** — specific event/data point (REQUIRED)
2. **The Data Context** — numbers from certified sources (REQUIRED)
3. **The Landscape** — who's working on this, what stage
4. **The Ripple Effects** — second/third-order consequences
5. **The Trade-Offs** — what's gained and lost, with data
6. **The Take** — editorial perspective earned through evidence

## Development Principles

- **Build incrementally** — one source → one analysis → one draft before adding complexity
- **Test each connector independently** — every module gets tests
- **Cache aggressively** — file-based caching with TTL to respect rate limits
- **Human in the loop** — pipeline drafts, Teo approves, nothing auto-publishes
- **Fail gracefully** — log and skip on errors, don't crash the pipeline
- **Version the prompts** — templates in `generation/prompts/` evolve over time

## Commands

```bash
python -m venv venv && source venv/Scripts/activate  # Windows
pip install -r requirements.txt
cp .env.example .env  # fill in API keys
python scripts/run_pipeline.py [--source ember|mongabay]
pytest tests/
```

## MCP & Skills

- **Notion MCP** — editorial queue tracking (use connector directly, not custom API code)
- **`/schedule`** — daily pipeline automation
- **`/skill-creator`** — custom editorial review skill (stored in `.claude/skills/`)

## Current Status

**Phase 1 in progress.** Ember connector done, RSS monitor next.

Done: scaffolding, Ember API connector (`pipeline/sources/`), file-based cache, 12 tests passing.
Next: Mongabay RSS monitor → enricher → drafter → orchestrator.

## Notes for Claude Code

- Teo has strong Python/data-science background, new to Claude Code — explain Claude Code specifics
- Prefer simple, readable code over clever abstractions
- Every new module comes with tests; new data sources follow the ember.py pattern
- Prompt templates reference Editorial Guidelines above
- If a design decision has trade-offs, explain them and let Teo choose
