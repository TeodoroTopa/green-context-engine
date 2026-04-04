# Energy Context Engine

## What This Project Is

An automated AI pipeline that monitors renewable energy news, enriches stories with data from multiple APIs, and publishes "energy intelligence briefs" on teodorotopa.com. An AI data strategist picks which data to fetch per article, an editor agent fact-checks drafts against source data, and a revision loop auto-corrects errors before publishing.

NOT a generic AI blog. Every post grounded in certified data, comparing countries to regional/global benchmarks, presenting trade-offs honestly. No fluff, no assertions without evidence.

## Architecture

```
RSS feeds → Monitor (keyword filter + dedup)
         → Data Strategist (AI picks which APIs/entities to query)
         → Enricher (fetches from Ember/EIA based on strategist plan)
         → Drafter (300-400 word brief with benchmark comparisons)
         → Editor (fact-checks draft against source data)
         → Revision loop (max 2 attempts to fix errors)
         → Notion (editorial queue + full content)
         → Approval (you mark "Approved" in Notion)
         → GitHub API push to website repo → live on teodorotopa.com
```

Key directories:
- `pipeline/sources/` — data connectors (Ember, EIA; follows BaseSource interface)
- `pipeline/monitors/` — RSS feed parsing + keyword filtering
- `pipeline/analysis/` — data strategist, catalog loader, enricher
- `pipeline/generation/` — drafter, editor, voice checker, prompts
- `pipeline/publishing/` — Notion API, approval polling, GitHub publishing
- `config/data_catalog/` — YAML catalogs describing each data source's entities
- `config/` — feeds.yaml, sources.yaml, publishing.yaml
- `tests/` — 63 tests covering all modules

## Data Sources

### Implemented
- **Ember API** — global electricity generation, carbon intensity, emissions for ~200 entities (countries, regions, economic groups like OECD/G20/ASEAN)
- **EIA Open Data API** — US electricity generation by fuel type (national + state level, all 50 states)
- **Global Forest Watch** — tree cover loss by country (2000-2024, geostore-based queries)
- **IUCN Red List v4** — threatened species counts by country and threat category (connector built, awaiting API key)
- **Mongabay RSS** — 3 feeds (energy, environment, climate-change)
- **Carbon Brief RSS** — climate/energy journalism
- **PV Magazine RSS** — solar industry news
- **CleanTechnica RSS** — clean energy news
- **Utility Dive RSS** — US energy industry
- **Electrek RSS** — EVs + energy storage
- **Renew Economy RSS** — Australian clean energy

### Adding a New Source
1. Drop a YAML in `config/data_catalog/` describing entities and data types
2. Create a connector in `pipeline/sources/` extending `BaseSource`
3. Register it in `pipeline/orchestrator.py` (check env var, add to sources dict)
4. The data strategist auto-discovers new catalogs — no prompt changes needed

### Planned
- Electricity Maps API, NOAA Climate Data

## Agent Pipeline (per story)

| Agent | Role | Claude calls |
|-------|------|-------------|
| **Data Strategist** | Reads article + all catalogs, picks which sources/entities to fetch | 1 |
| **Analyzer** | Summarizes data, suggests angles | 1 |
| **Drafter** | Writes 300-400 word brief with benchmark comparisons | 1 |
| **Editor** | Fact-checks draft against source data + story | 1 per attempt |
| **Reviser** | Fixes editor-flagged errors | 0-2 (only if editor fails) |

Total: 4-7 Claude calls per story (was 6-7 before refactor).

## Editorial Guidelines

### Always
- Ground every claim in data from a named, verifiable source
- Compare country data to global/regional benchmarks (World, OECD, ASEAN, etc.)
- Interpret data — never just present a number alone
- Present trade-offs honestly; one key trade-off per brief
- Explicitly state data years when they differ from story year
- Active voice, continuous prose (no section headers), 300-400 words

### Never
- Lazy adjectives without evidence ("unprecedented," "significant," "critical")
- Sweeping generalizations or flowery declarations
- Claims not traceable to the provided data or story
- Oversimplifications that change the meaning of trends

## Commands

```bash
source venv/Scripts/activate  # Windows
pip install -r requirements.txt

# Run pipeline (dev mode uses Claude Code subscription, not API billing)
PIPELINE_MODE=dev python scripts/run_pipeline.py --source mongabay --max-stories 1

# Publish approved drafts from Notion to website
python scripts/publish_approved.py         # for real
python scripts/publish_approved.py --dry-run  # preview only

# Tests
pytest tests/
```

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes (prod) | Claude API for production runs |
| `EMBER_API_KEY` | Yes | Ember electricity data (free — ember-energy.org) |
| `EIA_API_KEY` | Yes | EIA US electricity data (free — eia.gov/opendata/register.php) |
| `NOTION_TOKEN` | Optional | Editorial queue in Notion |
| `WEBSITE_GITHUB_TOKEN` | Optional | Publishes posts to website repo via GitHub API |
| `GFW_API_KEY` | Optional | Global Forest Watch tree cover loss (globalforestwatch.org) |
| `IUCN_API_KEY` | Optional | IUCN Red List threatened species (api.iucnredlist.org — applied, awaiting key) |
| `PIPELINE_MODE` | Optional | `dev` or `local` = route Claude calls through claude CLI; unset = Anthropic API |

## Publishing Flow

1. Pipeline runs → draft appears in Notion as "Drafted" or "Review"
2. Notion is the single source of truth — no local files needed
3. You change status to "Approved" in Notion (from phone or browser)
4. `publish_approved.py` reads content from Notion, commits to `TeodoroTopa/teodorotopa_personal_website` on main
5. Vercel auto-rebuilds, post live at teodorotopa.com/energy/[slug] within ~60 seconds
6. Duplicate prevention: checks Notion for existing URL before creating pages; updates existing files on republish

## Current Status

**Phases 1-5 complete. Smart data agent + editor with revision loop operational. 78 tests.**

## Local Scheduling

The pipeline runs locally via Windows Task Scheduler using `scripts/run_scheduled.bat`. All Claude calls route through `claude -p` (Claude Code subscription, no API billing). The batch script runs the pipeline then checks for approved drafts.

To set up: Task Scheduler → Create Task → Trigger: Daily → Action: Start `scripts\run_scheduled.bat` → Working dir: project root. Logs go to `logs/`.

Next: more news sources, Phase 7 (GFW/IUCN trade-off layer).

## Notes for Claude Code

- Teo has strong Python/data-science background — skip basic explanations
- Prefer simple, readable code over clever abstractions
- Every new module comes with tests
- New data sources: add YAML to `config/data_catalog/`, connector to `pipeline/sources/`
- If a design decision has trade-offs, explain them and let Teo choose
- Commit at every working checkpoint for easy rollback
