# Energy Context Engine

Automated pipeline: monitors energy/climate news → enriches with data from multiple APIs → AI drafts data-grounded briefs → AI editor fact-checks → human approves → publishes to teodorotopa.com.

## Architecture

```
RSS feeds → Monitor (keyword filter, Notion-based dedup)
         → Data Strategist (AI picks sources/entities/data_types to fetch)
         → Enricher (fetches from Ember, EIA, GFW, NOAA + formats for drafter)
         → Drafter (250-word brief with bold lead-in structure)
         → Editor (fact-checks every claim against source data)
         → Revision loop (max 2 attempts)
         → Notion editorial queue → human approval → GitHub API → Vercel → live
```

## Key Directories

- `pipeline/sources/` — data connectors (BaseSource interface)
- `pipeline/analysis/` — data strategist, enricher, catalog loader
- `pipeline/generation/` — drafter, editor, voice checker, prompts
- `pipeline/publishing/` — Notion API, GitHub publishing
- `config/data_catalog/` — YAML catalogs (strategist reads these to decide what to fetch)

## Data Sources

| Source | What it provides | Scope |
|--------|-----------------|-------|
| **Ember** | Electricity generation by fuel type, carbon intensity | ~200 countries |
| **EIA** | US electricity generation by fuel type with % breakdown | US national + 50 states |
| **GFW** | Tree cover loss, deforestation drivers (why), carbon emissions | Global, country-level |
| **NOAA** | Yearly temp, precip, heating/cooling degree days | 180+ countries, US states |
| **IUCN** | Threatened species by category | Global (awaiting API key) |

### Adding a New Source

1. YAML in `config/data_catalog/` — entities + data_types
2. Connector in `pipeline/sources/` extending `BaseSource`
3. Register in `pipeline/orchestrator.py`
4. Strategist auto-discovers from catalog

## Agent Pipeline

All agents use `claude-opus-4-6`. Per story: strategist (1 call) → analyzer (1) → drafter (1) → editor (1-3) → reviser (0-2). Total: 4-7 calls.

## Commands

```bash
# Run pipeline
PIPELINE_MODE=dev python scripts/run_pipeline.py --source mongabay --max-stories 1

# Standalone research (no Notion/publishing)
python scripts/research_story.py --url "..." --title "..." --summary "..."

# Publish approved
python scripts/publish_approved.py

# Tests
pytest tests/
```

## Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | prod | Claude API |
| `EMBER_API_KEY` | yes | Ember electricity data |
| `EIA_API_KEY` | yes | EIA US electricity data |
| `GFW_API_KEY` | optional | Global Forest Watch |
| `NOAA_API_KEY` | optional | NOAA climate data |
| `IUCN_API_KEY` | optional | IUCN Red List (awaiting key) |
| `NOTION_TOKEN` | optional | Editorial queue |
| `WEBSITE_GITHUB_TOKEN` | optional | Publish to website repo |
| `PIPELINE_MODE` | optional | `dev`/`local` = claude CLI proxy |

## Notes for Claude Code

- Teo is a senior data scientist — skip basic explanations
- Simple, readable code > clever abstractions
- Every new module comes with tests
- Commit at every working checkpoint
