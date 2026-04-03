# Energy Context Engine

## What This Project Is

An automated AI pipeline that monitors renewable energy news and public data sources, enriches stories with data and analysis, and publishes "energy intelligence briefs" on teodorotopa.com. The system runs daily, identifies noteworthy developments, gathers data context from multiple APIs, traces ripple effects, and drafts analysis posts for human review before publishing.

This is NOT a generic AI blog. Every post must be grounded in certified data sources, connect seemingly unrelated trends, and present trade-offs honestly. The editorial voice is informed, evidence-driven, and willing to hold contradictions (e.g., a solar farm that's great for decarbonization but bad for habitat). No fluff, no sweeping generalizations, no assertions without evidence.

## Architecture

```
energy-context-engine/          # This repo — the brain
├── pipeline/                   # Core data pipeline
│   ├── sources/                # Data source connectors (one module per source)
│   │   ├── ember.py            # Ember API — electricity data, carbon intensity
│   │   ├── eia.py              # EIA API — U.S. energy data
│   │   ├── electricity_maps.py # Electricity Maps — real-time grid data
│   │   ├── gfw.py              # Global Forest Watch — deforestation alerts
│   │   ├── noaa.py             # NOAA — climate/weather context
│   │   └── iucn.py             # IUCN Red List — biodiversity data
│   ├── monitors/               # News and data monitoring
│   │   ├── rss_monitor.py      # RSS feed parser (Mongabay, Carbon Brief, EIA)
│   │   └── data_monitor.py     # Detects notable movements in API data
│   ├── analysis/               # Analysis and enrichment engine
│   │   ├── enricher.py         # Pulls context data for a given story/trend
│   │   ├── landscape.py        # Maps who's working on a problem
│   │   ├── ripple.py           # Traces second/third-order effects
│   │   └── tradeoffs.py        # Cross-references energy + environmental data
│   ├── generation/             # Content generation
│   │   ├── drafter.py          # Generates draft posts from analysis
│   │   ├── prompts/            # Prompt templates for different post types
│   │   └── voice.py            # Editorial voice guidelines and constraints
│   └── orchestrator.py         # Main pipeline: monitor → analyze → draft
├── content/                    # Generated content (review queue)
│   ├── drafts/                 # Posts awaiting human review
│   ├── approved/               # Posts approved for publishing
│   └── published/              # Posts that have been pushed to website
├── data/                       # Local data cache
│   ├── cache/                  # Cached API responses (avoid redundant calls)
│   └── reference/              # Static reference data (country codes, etc.)
├── config/                     # Configuration
│   ├── sources.yaml            # API keys, endpoints, rate limits
│   ├── feeds.yaml              # RSS feed URLs and monitoring rules
│   └── publishing.yaml         # Publishing schedule and website connection
├── tests/                      # Test suite
├── scripts/                    # Utility scripts
│   ├── run_pipeline.py         # Manual pipeline trigger
│   ├── review_drafts.py        # CLI for reviewing and approving drafts
│   └── publish.py              # Push approved posts to website repo
├── .env.example                # Environment variable template
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Project metadata
└── CLAUDE.md                   # This file
```

The website repo (teodorotopa_personal_website) gets a new `/pages/energy/` route that reads published posts. The two repos connect through one of:
- Option A: This pipeline commits approved posts as JSON/MDX files to the website repo via GitHub API
- Option B: Posts stored in Vercel KV or a lightweight DB, website fetches at build/request time
- Option C (simplest for MVP): Pipeline outputs markdown files, manually copy to website repo

Start with Option C. Graduate to Option A once the pipeline is stable.

## Tech Stack

- **Language:** Python 3.11+
- **AI:** Claude API (via Anthropic SDK) for analysis and drafting
- **Data:** requests, pandas for API calls and data manipulation
- **RSS:** feedparser for news monitoring
- **Scheduling:** Initially manual; later `/schedule` skill + GitHub Actions
- **Testing:** pytest
- **Config:** pyyaml, python-dotenv

## Claude Ecosystem Integration

This project uses Claude Code in the terminal plus a few ecosystem tools where they genuinely improve the workflow. Don't add tools for the sake of it — every integration should solve a real problem.

### MCP Connectors
- **Notion** — Editorial queue. Stories are tracked in a Notion database from discovery ("Queued") through publication ("Published"). Claude can read/write to this database directly, and Teo can review the queue from his phone. This replaces what would otherwise be a custom CLI tool or local JSON file — Notion is better because it's accessible anywhere and already has the UI for filtering, sorting, and status tracking.

### Skills
- **`/schedule`** — Automates the pipeline to run daily. This is how the project becomes autonomous.
- **`/skill-creator`** — Used to create a custom editorial review skill that encodes the project's editorial guidelines into a reusable tool. This is worth doing because the same quality criteria (cite sources, no fluff, connect dots, present trade-offs) apply to every post and would otherwise need to be restated in every prompt or conversation.
- **`/xlsx`, `/docx`** — Use when you actually need a spreadsheet or document output. Don't generate these just to practice using the skill.

### Custom Skills (stored in project)
Custom skills created with `/skill-creator` should be stored in a `.claude/skills/` directory in this repo so they persist and are available in every session. Each skill has a SKILL.md file with instructions that Claude reads when the skill is invoked.

## Data Sources (Prioritized)

### Phase 1 (MVP)
- **Ember API** — Monthly global electricity data, carbon intensity. Free, CC-BY-4.0. Docs: https://ember-energy.org/data/api/
- **Mongabay RSS** — Environmental journalism feeds. Free. Feeds: https://www.mongabay.com/xml-list.html

### Phase 2
- **EIA Open Data API** — U.S. energy data (generation, capacity, prices). Free with registration. Docs: https://www.eia.gov/opendata/
- **Carbon Brief RSS** — Climate science and energy policy

### Phase 3
- **Electricity Maps API** — Real-time grid data. Free tier (100 req/month). Docs: https://app.electricitymaps.com/docs
- **Global Forest Watch API** — Deforestation alerts, land use. Free. Docs: https://data-api.globalforestwatch.org/

### Phase 4 (Trade-Off Layer)
- **IUCN Red List API** — Biodiversity/species data. Free with token.
- **NOAA Climate Data API** — Weather/climate context. Free with token.

## Editorial Guidelines

These are non-negotiable. They apply to all AI-generated content and to the prompts that produce it.

### Always
- Ground every claim in data from a named, verifiable source
- Interpret data — never just present a number and expect it to speak for itself
- Connect seemingly unrelated trends (energy policy → land use → biodiversity → economics)
- Present trade-offs: if something is good for decarbonization but bad for habitat, say both
- Use active voice, clear paragraph structure (topic → evidence → interpretation → tie-in)
- Show WHY something matters rather than asserting that it does

### Never
- Use lazy adjectives without earning them ("unprecedented," "important," "critical")
- Make sweeping generalizations that discount implementation difficulty
- Use a single anecdote to prove a universal pattern
- Write flowery, empty declarations ("In an era of unprecedented change...")
- Filter information to steer the reader toward a predetermined conclusion
- Inflate credentials or tell the reader what to think before presenting evidence
- Use jargon without context when writing for a general audience

### Post Structure
Each energy intelligence brief follows this general structure:
1. **The Hook** — A specific news event, data point, or trend that's the entry point
2. **The Data Context** — Relevant numbers from certified sources that frame the story
3. **The Landscape** — Who's working on this, what's been tried, what stage things are at
4. **The Ripple Effects** — Second and third-order consequences (cascade reasoning)
5. **The Trade-Offs** — What's gained and what's lost, with data on both sides
6. **The Take** — Teo's editorial perspective, earned through the preceding evidence

Not every post needs all six sections. The hook and data context are mandatory; the rest depend on what the story calls for.

## Development Principles

- **Build incrementally.** Get one data source → one analysis → one draft post working end-to-end before adding complexity.
- **Test each source connector independently.** Every API module should have tests that verify data retrieval and parsing.
- **Cache aggressively.** API rate limits are real. Cache responses locally and only re-fetch when data is stale.
- **Human in the loop.** No post publishes without human review. The pipeline drafts; Teo approves.
- **Fail gracefully.** If an API is down or returns unexpected data, log the issue and skip — don't crash the whole pipeline.
- **Version the prompts.** Prompt templates in `generation/prompts/` should be versioned and iterable. What makes a good energy brief will evolve.

## Commands

```bash
# Set up the project
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env  # then fill in API keys

# Run the pipeline manually
python scripts/run_pipeline.py

# Run for a specific source only
python scripts/run_pipeline.py --source ember
python scripts/run_pipeline.py --source mongabay

# Review drafts
python scripts/review_drafts.py

# Publish approved posts
python scripts/publish.py

# Run tests
pytest tests/
```

## Environment Variables

```
ANTHROPIC_API_KEY=         # For Claude API calls
EMBER_API_KEY=             # If required (currently free without key)
EIA_API_KEY=               # Register at eia.gov/opendata
ELECTRICITY_MAPS_TOKEN=    # Free tier token
GFW_API_KEY=               # Global Forest Watch
NOAA_TOKEN=                # NOAA CDO token
IUCN_TOKEN=                # IUCN Red List API token
GITHUB_TOKEN=              # For pushing posts to website repo (Phase 2+)
```

## Current Status

**Phase:** Session 1 complete — project scaffolded and Ember API connector built with tests.

**What's done:**
- Full directory structure created
- `pyproject.toml`, `requirements.txt`, `.env.example`, `.gitignore` in place
- `pipeline/sources/base.py` — abstract base class for all source connectors
- `pipeline/sources/cache.py` — file-based response caching with TTL
- `pipeline/sources/ember.py` — Ember API connector (generation, carbon intensity, monthly trends)
- `config/sources.yaml` — Ember endpoint configuration
- 12 tests passing (`tests/test_cache.py`, `tests/test_ember.py`)

**Next up:** Session 2 — Mongabay RSS monitor (`pipeline/monitors/rss_monitor.py`)

## Notes for Claude Code

When working on this project:
- Teo is building Claude Code skills from beginner level. Explain what you're doing and why as you build.
- Prefer simple, readable code over clever abstractions. This is a learning project.
- Every new module should come with tests.
- When adding a new data source, follow the pattern established by the first one (ember.py).
- When writing or editing prompt templates, refer to the Editorial Guidelines above.
- The project owner (Teo) has a strong background in data science, PySpark, SQL, and Python. He's new to Claude Code specifically, not to programming.
- If a design decision has trade-offs, explain them and let Teo choose.
- When interacting with Notion, use the MCP connector directly rather than writing custom API code. It's already authenticated and available.
- If you notice a pattern being repeated across sessions (same instructions, same quality checks), suggest creating a custom skill — but only if the repetition is real, not hypothetical.
- When automation is needed, consider the `/schedule` skill before external cron or GitHub Actions. Use whichever is simpler for the specific case.
